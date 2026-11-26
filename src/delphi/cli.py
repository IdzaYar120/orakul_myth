from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel

from delphi.config import settings
from delphi.db.repo import seed_database
from delphi.eval.run import run_evaluation
from delphi.rag.oracle import OracleService

app = typer.Typer(
    name="delphi",
    help="Дельфійський оракул — CLI для управління базою знань, інгестом та запитами",
)
console = Console()


@app.command()
def seed():
    """Initialize SQLite database and populate with initial seed data."""
    console.print("[bold yellow]Ініціалізація бази даних та сідування...[/bold yellow]")
    counts = seed_database()
    console.print(
        f"[bold green]Нових записів:[/bold green] "
        f"{counts['entities']} сутностей, {counts['places']} місць, "
        f"{counts['relations']} зв'язків, {counts['myths']} міфів, "
        f"{counts['routes']} маршрутів, {counts['aliases']} аліасів; "
        f"видалено застарілих: {counts['removed']}. Змінені записи оновлено."
    )


@app.command()
def ingest(
    source: list[str] = typer.Option(
        None, "--source", "-s", help="id джерела з data/sources.yaml (можна кілька)"
    ),
    force_download: bool = typer.Option(False, help="Завантажити тексти заново"),
):
    """Download texts, parse TEI, chunk, tag entities and build Chroma + BM25 indexes."""
    from delphi.ingest.pipeline import run_ingest

    console.print("[bold cyan]Офлайн-інгест корпусу...[/bold cyan]")
    reports, stats = run_ingest(
        source_ids=source or None,
        force_download=force_download,
        progress=lambda msg: console.print(f"  [dim]{msg}[/dim]"),
    )
    for r in reports:
        console.print(
            f"  [green]{r.source_id}[/green]: {r.sections} розділів -> {r.chunks} чанків "
            f"(~{r.avg_tokens} токенів), із сутностями: {r.tagged}"
        )
    console.print(
        f"[bold green]Готово:[/bold green] {stats.passages} уривків, нових ембеддингів: "
        f"{stats.embedded}, видалено застарілих: {stats.removed}. Індекс: {settings.index_dir}"
    )


@app.command()
def ask(
    question: str = typer.Argument(..., help="Питання до Дельфійського оракула"),
    style: str = typer.Option("піфія", "--style", "-s", help="Стиль: 'піфія' або 'науковий'"),
):
    """Ask the Oracle directly from the command line."""
    console.print(Panel(f"[bold cyan]Питання:[/bold cyan] {question} (стиль: {style})"))
    ans = OracleService().ask(question, style=style)

    if ans.error:
        console.print(f"[yellow]{ans.error}[/yellow]")
    if ans.text:
        console.print(Panel(ans.text, title="Відповідь Піфії", border_style="magenta"))

    if ans.citations:
        console.print("[bold]Джерела:[/bold]")
        for c in ans.citations:
            mark = "*" if c.cited else " "
            console.print(f" {mark}[{c.num}] {c.ref} ({c.translator})")
    if ans.invalid_citations:
        console.print(f"[red]Неіснуючі посилання у відповіді: {ans.invalid_citations}[/red]")
    if ans.entities:
        console.print(f"[dim]Розпізнані сутності: {', '.join(ans.entities)}[/dim]")


@app.command("eval")
def eval_cmd(
    llm: bool = typer.Option(False, "--llm", help="Також відповісти LLM: відмови, посилання"),
    judge: bool = typer.Option(
        False, "--judge", help="LLM-суддя: faithfulness і покриття фактів (вмикає --llm)"
    ),
    question_id: list[str] = typer.Option(None, "--id", help="Лише ці питання (q001 ...)"),
    qtype: list[str] = typer.Option(
        None, "--type", help="Лише цей тип: factual|multi_hop|conflicting|negative"
    ),
    limit: int = typer.Option(None, help="Перші N питань"),
    out: Path = typer.Option(None, help="Куди записати JSON-звіт (типово eval/report-*.json)"),
    resume: bool = typer.Option(
        False, "--resume", help="Продовжити перерваний прогін (разом з --out його звіту)"
    ),
    note: str = typer.Option("", help="Примітка до рядка в data/eval/history.csv"),
):
    """Evaluate on the golden set: Hit@5, MRR, refusals, citations, faithfulness."""
    try:
        run_evaluation(
            with_llm=llm,
            with_judge=judge,
            ids=question_id or None,
            types=qtype or None,
            limit=limit,
            out=out,
            resume=resume,
            note=note,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command("check-refs")
def check_refs(
    show_ok: bool = typer.Option(False, help="Показати й підтверджені посилання"),
):
    """Verify source_ref of seed relations against the ingested corpus."""
    from collections import Counter

    from sqlmodel import Session

    from delphi.db.repo import engine
    from delphi.eval.refs import check_relation_refs

    with Session(engine) as session:
        results = check_relation_refs(session)
    counts = Counter(r.status for r in results)
    labels = {
        "ok": "[green]підтверджено[/green]",
        "entity_missing": "[yellow]місце є, але сутність не згадано[/yellow]",
        "ref_not_found": "[red]місце не знайдено[/red]",
        "not_ingested": "[dim]джерело ще не в корпусі / Wikidata / manual[/dim]",
    }
    for status in ("ok", "entity_missing", "ref_not_found", "not_ingested"):
        console.print(f"{labels[status]}: {counts.get(status, 0)}")
    for r in results:
        if r.status in ("entity_missing", "ref_not_found") or (show_ok and r.status == "ok"):
            console.print(
                f"  {r.status:15} {r.src_id} {r.rel} {r.dst_id} [{r.source_ref}] {r.detail}"
            )


wikidata_app = typer.Typer(help="Імпорт сутностей і місць з Wikidata + Pleiades (етап 1)")
app.add_typer(wikidata_app, name="wikidata")


@wikidata_app.command("candidates")
def wikidata_candidates(
    min_sitelinks: int = typer.Option(25, help="Мінімальна кількість статей у Вікіпедіях"),
    out: Path | None = typer.Option(None, help="Куди записати YAML (за замовчуванням stdout)"),
):
    """List mythological figures ranked by prominence (SPARQL) to choose the selection."""
    from delphi.ingest.wikidata import WikidataClient, fetch_candidates

    cands = fetch_candidates(WikidataClient(), min_sitelinks=min_sitelinks)
    if out:
        out.write_text(yaml.safe_dump(cands, allow_unicode=True, sort_keys=False), "utf-8")
        console.print(f"[green]{len(cands)} кандидатів записано в {out}[/green]")
        return
    for c in cands:
        console.print(
            f"{c['qid']:>10}  {c['sitelinks']:>4}  {c['name_en'] or '-':<28} "
            f"{c['name_uk'] or '-':<28} {','.join(c['types'])}"
        )


@wikidata_app.command("pull")
def wikidata_pull(
    selection: Path | None = typer.Option(None, help="data/wikidata/selection.yaml"),
    out: Path | None = typer.Option(None, help="data/wikidata/snapshot.yaml"),
):
    """Fetch labels, aliases, family relations and coordinates for the selection."""
    from delphi.ingest.wikidata import Selection, WikidataClient, build_snapshot, default_dir

    sel_path = selection or default_dir() / "selection.yaml"
    out_path = out or default_dir() / "snapshot.yaml"
    sel = Selection.load(sel_path)
    console.print(f"Завантаження {len(sel.all)} сутностей з Wikidata/Pleiades...")
    snap = build_snapshot(WikidataClient(), sel)
    out_path.write_text(
        yaml.safe_dump(snap, allow_unicode=True, sort_keys=False, width=100), "utf-8"
    )
    missing = [e["id"] for e in snap["entities"] if e.get("missing")]
    no_coords = [
        e["id"]
        for e in snap["entities"]
        if e.get("type") == "place" and e.get("lat") is None and e.get("certainty") != "none"
    ]
    console.print(
        f"[green]Знімок: {len(snap['entities'])} сутностей, "
        f"{len(snap['relations'])} зв'язків -> {out_path}[/green]"
    )
    if missing:
        console.print(f"[red]Не знайдено у Wikidata: {', '.join(missing)}[/red]")
    if no_coords:
        console.print(f"[yellow]Місця без координат: {', '.join(no_coords)}[/yellow]")


@wikidata_app.command("draft")
def wikidata_draft(
    snapshot: Path | None = typer.Option(None, help="data/wikidata/snapshot.yaml"),
    seed_dir: Path | None = typer.Option(None, help="data/seed"),
):
    """Append entries missing from the seed YAML (existing entries are never modified)."""
    from delphi.ingest.wikidata import append_yaml, default_dir, draft_entries, load_rejected

    snap_path = snapshot or default_dir() / "snapshot.yaml"
    seed = seed_dir or settings.data_dir / "seed"
    with open(snap_path, encoding="utf-8") as f:
        snap = yaml.safe_load(f)
    rejected = load_rejected(default_dir() / "rejected.yaml")
    ents, places, rels = draft_entries(snap, seed, rejected)
    header = "draft from Wikidata: перевірити назви, описи, source_ref"
    append_yaml(seed / "entities.yaml", ents, header)
    append_yaml(seed / "places.yaml", places, header)
    append_yaml(seed / "relations.yaml", rels, header)
    console.print(
        f"[green]Додано чернеток: {len(ents)} сутностей, {len(places)} місць, "
        f"{len(rels)} зв'язків.[/green] Відредагуйте data/seed/*.yaml і запустіть `delphi seed`."
    )


if __name__ == "__main__":
    app()
