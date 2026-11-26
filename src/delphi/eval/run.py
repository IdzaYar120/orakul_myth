"""Quality evaluation on the golden set (`delphi eval`).

Retrieval metrics need no LLM and run in seconds:

* **Hit@5** — an expected reference is among the passages the LLM sees (after reranking);
* **Hit@20** / **MRR@20** — the same over the retrieval candidates, and how high it ranks;
* **entity recall** — share of the expected entities the linker found in the question.

With ``--llm`` every question is answered by the configured model:

* **refusal accuracy** — trap questions refused, answerable ones not refused;
* **citation validity** — answers that cite at least one passage and no non-existent [n];
* **cited hit** — a cited passage contains an expected reference.

With ``--judge`` an LLM grades **faithfulness** (every claim is supported by the passages) and
**fact coverage** (share of ``expected_facts`` present in the answer). A local model judging
its own answers is biased, so treat these two as a trend between runs, not absolute numbers.

Every question's result is appended to ``<report>.partial.jsonl`` as soon as it is ready, so an
interrupted run (a power cut, Ollama restarting) continues with ``--resume --out <report>``.
A full run (no ``--id``/``--type``/``--limit``) adds one row to ``data/eval/history.csv``, the
metrics history kept in git.
"""

import csv
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from delphi.config import settings
from delphi.eval.refs import ref_contains
from delphi.rag.llm import LLMUnavailableError
from delphi.rag.oracle import OracleService, PreparedQuestion
from delphi.rag.prompts import REFUSAL_PHRASE

console = Console()
TYPES = ("factual", "multi_hop", "conflicting", "negative")
HISTORY_FIELDS = [
    "date",
    "commit",
    "mode",
    "note",
    "llm_model",
    "query_translation",
    "rerank_enabled",
    "n",
    "hit@5",
    "hit@20",
    "mrr@20",
    "entity_recall",
    "refusal_accuracy",
    "trap_refused",
    "false_refusal",
    "citation_validity",
    "cited_hit",
    "faithfulness",
    "fact_coverage",
    "avg_seconds",
]


class GoldenQuestion(BaseModel):
    id: str
    question_uk: str
    type: str  # factual | multi_hop | conflicting | negative
    style: str = "науковий"
    expected_entity_ids: list[str] = Field(default_factory=list)
    # Point references ("Apollod. 2.4.2", "Hes. Theog. 280", "Hom. Il. 18.478"); any one is enough
    expected_refs: list[str] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)
    should_refuse: bool = False
    notes: str | None = None


@dataclass
class QuestionResult:
    id: str
    type: str
    question: str
    should_refuse: bool
    rank: int | None = None  # 1-based rank of the first candidate with an expected ref
    hit_context: bool | None = None  # None: no expected refs to check
    entity_recall: float | None = None
    context_refs: list[str] = field(default_factory=list)
    retrieval_grounded: bool = True
    # --llm
    answer: str | None = None
    refused: bool | None = None
    citations_valid: bool | None = None
    cited_hit: bool | None = None
    error: str | None = None
    seconds: float | None = None
    # --judge
    faithful: bool | None = None
    fact_coverage: float | None = None
    judge_comment: str | None = None


def load_golden(path: Path | None = None) -> list[GoldenQuestion]:
    golden = path or settings.data_dir / "eval" / "golden.yaml"
    with open(golden, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    questions = [GoldenQuestion(**q) for q in data.get("questions", [])]
    ids = [q.id for q in questions]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Повторені id у golden set: {sorted(duplicates)}")
    unknown = {q.type for q in questions} - set(TYPES)
    if unknown:
        raise ValueError(f"Невідомі типи питань: {sorted(unknown)}")
    return questions


def covers(passage_ref: str, expected_refs: list[str]) -> bool:
    return any(ref_contains(passage_ref, ref) for ref in expected_refs)


def uncovered_refs(questions: list[GoldenQuestion], passage_refs: list[str]) -> list[str]:
    """Expected refs no passage of the corpus covers: typos, or a source not ingested yet."""
    return [
        f"{q.id}: {ref}"
        for q in questions
        for ref in q.expected_refs
        if not any(ref_contains(p, ref) for p in passage_refs)
    ]


def _corpus_refs() -> list[str]:
    from sqlmodel import Session, select

    from delphi.db.models import Passage
    from delphi.db.repo import engine

    with Session(engine) as session:
        return list(session.exec(select(Passage.ref)).all())


def retrieval_result(q: GoldenQuestion, prepared: PreparedQuestion) -> QuestionResult:
    result = QuestionResult(
        id=q.id,
        type=q.type,
        question=q.question_uk,
        should_refuse=q.should_refuse,
        context_refs=[p.ref for p in prepared.passages],
        retrieval_grounded=prepared.grounded,
    )
    if q.expected_refs:
        ranked = prepared.candidates or prepared.passages
        result.rank = next(
            (i for i, p in enumerate(ranked, 1) if covers(p.ref, q.expected_refs)), None
        )
        result.hit_context = any(covers(p.ref, q.expected_refs) for p in prepared.passages)
    if q.expected_entity_ids:
        found = set(prepared.entity_ids)
        result.entity_recall = sum(e in found for e in q.expected_entity_ids) / len(
            q.expected_entity_ids
        )
    return result


JUDGE_PROMPT = """Ти — суворий екзаменатор. Оціни відповідь на питання про грецьку міфологію.

Уривки джерел (англійською), на які мала спиратися відповідь:
{context}

Питання: {question}

Відповідь:
{answer}

Очікувані факти (по одному на рядок):
{facts}

1. faithful: true, якщо КОЖНЕ твердження відповіді підтверджене уривками; false, якщо є хоч одне
   твердження, якого в уривках немає (вигадка або знання поза джерелами).
2. facts: для кожного очікуваного факту true/false — чи він є у відповіді (за змістом).
Поверни лише JSON без пояснень поза ним:
{{"faithful": true, "facts": [true, false], "comment": "коротко, що не так"}}"""

_JSON = re.compile(r"\{.*\}", re.S)


def judge_answer(
    judge: BaseChatModel, q: GoldenQuestion, prepared: PreparedQuestion, answer: str
) -> tuple[bool | None, float | None, str]:
    facts = q.expected_facts or []
    prompt = JUDGE_PROMPT.format(
        context=prepared.context or "(немає)",
        question=q.question_uk,
        answer=answer,
        facts="\n".join(facts) or "(немає)",
    )
    raw = str(judge.invoke(prompt).content)
    match = _JSON.search(raw)
    if not match:
        return None, None, f"judge: no JSON in {raw[:120]!r}"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, None, f"judge: bad JSON {match.group(0)[:120]!r}"
    flags = [bool(x) for x in data.get("facts", [])][: len(facts)]
    coverage = sum(flags) / len(facts) if facts and flags else None
    faithful = data.get("faithful")
    return (
        bool(faithful) if faithful is not None else None,
        coverage,
        str(data.get("comment", "")),
    )


def evaluate(
    questions: list[GoldenQuestion],
    oracle: OracleService | None = None,
    with_llm: bool = False,
    judge: BaseChatModel | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    done: dict[str, QuestionResult] | None = None,
    on_result: Callable[[QuestionResult], None] = lambda _r: None,
) -> list[QuestionResult]:
    """Evaluate every question; results already in ``done`` (a resumed run) are reused."""
    oracle = oracle or OracleService()
    done = done or {}
    results = []
    for n, q in enumerate(questions, 1):
        if q.id in done:
            results.append(done[q.id])
            continue
        progress(f"[{n}/{len(questions)}] {q.id} {q.question_uk}")
        prepared = oracle.prepare(q.question_uk, style=q.style)
        result = retrieval_result(q, prepared)
        if with_llm:
            started = time.perf_counter()
            try:
                answer = oracle.finalize(prepared, "".join(oracle.stream(prepared)))
            except LLMUnavailableError as exc:  # Ollama down: stop early, it fails for all
                raise SystemExit(str(exc)) from exc
            result.seconds = round(time.perf_counter() - started, 1)
            result.answer = answer.text
            result.error = answer.error
            result.refused = REFUSAL_PHRASE.lower() in answer.text.lower()
            cited = [c for c in answer.citations if c.cited]
            if not result.refused and answer.error is None:
                result.citations_valid = bool(cited) and not answer.invalid_citations
                if q.expected_refs:
                    result.cited_hit = any(covers(c.ref, q.expected_refs) for c in cited)
            if judge is not None and answer.error is None and not result.refused:
                result.faithful, result.fact_coverage, result.judge_comment = judge_answer(
                    judge, q, prepared, answer.text
                )
        results.append(result)
        on_result(result)
    return results


def load_partial(path: Path) -> dict[str, QuestionResult]:
    """Results of an interrupted run (one JSON object per line; a torn last line is skipped)."""
    done: dict[str, QuestionResult] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        done[data["id"]] = QuestionResult(**data)
    return done


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def append_history(
    summary: dict[str, float | int | None],
    mode: str,
    note: str = "",
    path: Path | None = None,
) -> Path:
    """One row per full run in data/eval/history.csv (tracked in git): the metrics over time."""
    target = path or settings.data_dir / "eval" / "history.csv"
    new_file = not target.exists()
    row = {
        "date": datetime.now().isoformat(timespec="minutes"),
        "commit": _commit(),
        "mode": mode,
        "note": note,
        "llm_model": settings.llm_model if "LLM" in mode else "",
        "query_translation": settings.query_translation,
        "rerank_enabled": settings.rerank_enabled,
        **{k: summary.get(k) for k in HISTORY_FIELDS if k in summary},
    }
    with open(target, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in HISTORY_FIELDS})
    return target


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _share(flags: list[bool]) -> float | None:
    return _mean([1.0 if f else 0.0 for f in flags])


def summarize(results: list[QuestionResult]) -> dict[str, float | int | None]:
    with_refs = [r for r in results if r.hit_context is not None]
    answered = [r for r in results if r.refused is not None]
    positive = [r for r in answered if not r.should_refuse]
    negative = [r for r in answered if r.should_refuse]
    return {
        "n": len(results),
        "hit@5": _share([bool(r.hit_context) for r in with_refs]),
        "hit@20": _share([r.rank is not None for r in with_refs]),
        "mrr@20": _mean([1 / r.rank if r.rank else 0.0 for r in with_refs]),
        "entity_recall": _mean([r.entity_recall for r in results if r.entity_recall is not None]),
        "refusal_accuracy": _share([r.refused == r.should_refuse for r in answered]),
        "trap_refused": _share([bool(r.refused) for r in negative]),
        "false_refusal": _share([bool(r.refused) for r in positive]),
        "citation_validity": _share(
            [r.citations_valid for r in answered if r.citations_valid is not None]
        ),
        "cited_hit": _share([r.cited_hit for r in answered if r.cited_hit is not None]),
        "faithfulness": _share([r.faithful for r in results if r.faithful is not None]),
        "fact_coverage": _mean([r.fact_coverage for r in results if r.fact_coverage is not None]),
        "avg_seconds": _mean([r.seconds for r in answered if r.seconds is not None]),
    }


def _fmt(value: float | int | None, key: str) -> str:
    if value is None:
        return "—"
    if key in ("n",):
        return str(value)
    if key == "avg_seconds":
        return f"{value:.1f}"
    return f"{value:.0%}" if isinstance(value, float) and value <= 1 else str(value)


def print_report(results: list[QuestionResult], title: str) -> dict[str, dict]:
    groups = {"усі": results} | {
        t: [r for r in results if r.type == t] for t in TYPES if any(r.type == t for r in results)
    }
    summaries = {name: summarize(rs) for name, rs in groups.items()}
    keys = [k for k in summaries["усі"] if any(s[k] is not None for s in summaries.values())]
    table = Table(title=title)
    table.add_column("метрика")
    for name in groups:
        table.add_column(name, justify="right")
    for key in keys:
        table.add_row(key, *(_fmt(summaries[name][key], key) for name in groups))
    console.print(table)

    misses = [r for r in results if r.hit_context is False]
    if misses:
        console.print("[yellow]Очікуване місце не потрапило в контекст (Hit@5 = 0):[/yellow]")
        for r in misses:
            where = f"ранг {r.rank}" if r.rank else "немає в топ-20"
            console.print(f"  {r.id} [{r.type}] {r.question} — {where}")
    wrong = [r for r in results if r.refused is not None and r.refused != r.should_refuse]
    if wrong:
        console.print("[yellow]Неправильна відмова / відповідь на пастку:[/yellow]")
        for r in wrong:
            kind = "відповів на пастку" if r.should_refuse else "відмовив"
            console.print(f"  {r.id} {kind}: {r.question}")
    return summaries


def run_evaluation(
    golden_path: Path | None = None,
    with_llm: bool = False,
    with_judge: bool = False,
    ids: list[str] | None = None,
    types: list[str] | None = None,
    limit: int | None = None,
    out: Path | None = None,
    oracle: OracleService | None = None,
    judge: BaseChatModel | None = None,
    resume: bool = False,
    note: str = "",
    history: Path | None = None,
) -> dict[str, dict]:
    """Evaluate on the golden set, print the report, save per-question results as JSON."""
    if resume and out is None:
        raise ValueError("--resume потребує --out <звіт.json> перерваного прогону")
    questions = load_golden(golden_path)
    full_run = not (ids or types or limit)
    if ids:
        questions = [q for q in questions if q.id in set(ids)]
    if types:
        questions = [q for q in questions if q.type in set(types)]
    if limit:
        questions = questions[:limit]
    if not questions:
        raise ValueError("Немає питань для оцінки (перевірте --id / --type)")

    if with_judge:
        from delphi.rag.llm import get_chat_model

        with_llm = True
        judge = judge or get_chat_model(temperature=0.0)

    missing = uncovered_refs(questions, _corpus_refs())
    if missing:
        console.print(
            f"[yellow]{len(missing)} очікуваних посилань не покриває жоден уривок корпусу "
            f"(опечатка або джерело не проіндексоване):[/yellow] {', '.join(missing)}"
        )

    mode = "retrieval" + (" + LLM" if with_llm else "") + (" + judge" if judge else "")
    target = out or Path("eval") / f"report-{datetime.now():%Y%m%d-%H%M%S}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial.jsonl")
    done = load_partial(partial) if resume else {}
    if not resume:
        partial.unlink(missing_ok=True)
    console.print(
        f"[bold]Golden set: {len(questions)} питань; режим: {mode}"
        + (f"; продовження: готово {len(done)}" if resume else "")
        + "[/bold]"
    )

    def save(result: QuestionResult) -> None:
        with open(partial, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

    results = evaluate(
        questions,
        oracle=oracle,
        with_llm=with_llm,
        judge=judge,
        progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
        done=done,
        on_result=save,
    )
    summaries = print_report(results, f"Оцінка ({mode})")

    report = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "settings": {
            "llm_model": settings.llm_model if with_llm else None,
            "embedding_model": settings.embedding_model,
            "rerank_enabled": settings.rerank_enabled,
            "min_relevance": settings.min_relevance,
            "retrieve_k": settings.retrieve_k,
            "context_k": settings.context_k,
            "query_translation": settings.query_translation,
            "entity_boost": settings.entity_boost,
        },
        "summary": summaries,
        "results": [asdict(r) for r in results],
    }
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.unlink(missing_ok=True)
    console.print(f"Звіт: {target}")
    if full_run:
        console.print(f"Історія метрик: {append_history(summaries['усі'], mode, note, history)}")
    return summaries
