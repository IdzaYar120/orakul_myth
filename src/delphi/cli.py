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
def ingest():
    """Download texts, chunk, tag entities, and build indexes."""
    console.print("[bold cyan]Запуск офлайн-інгесту корпусів...[/bold cyan]")
    console.print("[yellow]Етап офлайн-інгесту буде розгорнуто в Етапі 3.[/yellow]")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Питання до Дельфійського оракула"),
    style: str = typer.Option("піфія", "--style", "-s", help="Стиль: 'піфія' або 'науковий'"),
):
    """Ask the Oracle directly from the command line."""
    console.print(Panel(f"[bold cyan]Питання:[/bold cyan] {question} (стиль: {style})"))
    oracle = OracleService()
    ans = oracle.ask(question, style=style)

    console.print(Panel(ans.text, title="Відповідь Піфії", border_style="magenta"))

    if ans.citations:
        console.print("[bold]Джерела цитат:[/bold]")
        for c in ans.citations:
            console.print(f"  [{c.num}] {c.author}, {c.work} ({c.ref})")

    if ans.entities:
        console.print(f"[dim]Розпізнані сутності: {', '.join(ans.entities)}[/dim]")


@app.command()
def eval():
    """Run evaluation benchmarks against the golden set."""
    console.print("[bold blue]Запуск тестування на golden set...[/bold blue]")
    run_evaluation()


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
    from delphi.ingest.wikidata import append_yaml, default_dir, draft_entries

    snap_path = snapshot or default_dir() / "snapshot.yaml"
    seed = seed_dir or settings.data_dir / "seed"
    with open(snap_path, encoding="utf-8") as f:
        snap = yaml.safe_load(f)
    ents, places, rels = draft_entries(snap, seed)
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
