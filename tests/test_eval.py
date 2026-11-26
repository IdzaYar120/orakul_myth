"""Golden set validity and the evaluation metrics (`delphi eval`), without a real LLM."""

import json
from pathlib import Path

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlmodel import Session

from delphi.eval.refs import ref_contains
from delphi.eval.run import (
    TYPES,
    GoldenQuestion,
    evaluate,
    judge_answer,
    load_golden,
    summarize,
    uncovered_refs,
)
from delphi.rag.prompts import REFUSAL_PHRASE
from tests.test_oracle_service import PASSAGES, _oracle


def test_repo_golden_set_is_well_formed():
    questions = load_golden()
    assert 60 <= len(questions) <= 100
    assert {q.type for q in questions} == set(TYPES)
    for q in questions:
        if q.type == "negative":
            assert q.should_refuse and not q.expected_refs, q.id
        else:
            assert not q.should_refuse and q.expected_refs and q.expected_facts, q.id
    # every point reference is parseable by the matcher (matches itself)
    for q in questions:
        for ref in q.expected_refs:
            assert ref_contains(ref, ref), (q.id, ref)


def test_load_golden_rejects_duplicates(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    q = {"id": "q1", "question_uk": "?", "type": "factual"}
    path.write_text(yaml.safe_dump({"questions": [q, q]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Повторені"):
        load_golden(path)


@pytest.mark.parametrize(
    ("passage", "target", "expected"),
    [
        ("Hes. Theog. 912–929", "Hes. Theog. 918", True),
        ("Hes. Theog. 912–925", "Hes. Theog. 929", True),  # last block covers ~5 lines
        ("Hes. Theog. 912–925", "Hes. Theog. 940", False),
        ("Hom. Il. 18.475–18.500", "Hom. Il. 18.478", True),
        ("Hom. Il. 18.475–18.500", "Hom. Il. 19.1", False),
        ("Apollod. 2.4.1–2.4.3", "Apollod. 2.4.2", True),
        ("Apollod. 2.4.2 (1/2)", "Apollod. 2.4.2", True),
        ("Ap. Rhod. 1§115–1§118", "Ap. Rhod. 1§116", True),
        ("Ap. Rhod. 1§115–1§118", "Ap. Rhod. 2§116", False),
        ("Hom. Hymn 3 Ap. 280–300", "Hom. Hymn 3 Ap. 285", True),
        ("Hom. Hymn 3 Ap. 280–300", "Hom. Hymn 2 Dem. 285", False),
    ],
)
def test_ref_contains(passage: str, target: str, expected: bool):
    assert ref_contains(passage, target) is expected


def test_uncovered_refs():
    q = GoldenQuestion(
        id="q1", question_uk="?", type="factual", expected_refs=["Apollod. 1.4.1", "Paus. 1.1.1"]
    )
    assert uncovered_refs([q], ["Apollod. 1.4.1", "Hes. Theog. 1–20"]) == ["q1: Paus. 1.1.1"]


GOLDEN = [
    GoldenQuestion(
        id="q1",
        question_uk="Хто батьки Аполлона?",
        type="factual",
        expected_entity_ids=["apollo", "zeus"],
        expected_refs=["Apollod. 1.4.1"],  # the 2nd passage
        expected_facts=["Зевс", "Лето"],
    ),
    GoldenQuestion(
        id="q2",
        question_uk="Який номер телефону в Зевса?",
        type="negative",
        should_refuse=True,
    ),
]


def test_retrieval_metrics_without_llm(seeded_session: Session):
    results = evaluate(GOLDEN, oracle=_oracle(seeded_session, PASSAGES))
    first = results[0]
    assert first.rank == 2 and first.hit_context is True
    assert first.entity_recall == 0.5  # the question names Apollo, not Zeus
    assert first.answer is None
    summary = summarize(results)
    assert summary["hit@5"] == 1.0 and summary["mrr@20"] == 0.5
    assert summary["refusal_accuracy"] is None  # no LLM run


def test_llm_metrics(seeded_session: Session):
    oracle = _oracle(
        seeded_session,
        PASSAGES,
        responses=[
            "Аполлон — син Зевса і Лето [2], а ще [7].",  # q1: one valid, one invalid citation
            f"{REFUSAL_PHRASE}.",  # q2: trap refused
        ],
    )
    results = evaluate(GOLDEN, oracle=oracle, with_llm=True)
    q1, q2 = results
    assert q1.refused is False and q1.cited_hit is True
    assert q1.citations_valid is False  # [7] does not exist
    assert q2.refused is True
    summary = summarize(results)
    assert summary["refusal_accuracy"] == 1.0
    assert summary["trap_refused"] == 1.0 and summary["false_refusal"] == 0.0


def test_judge_parses_json(seeded_session: Session):
    oracle = _oracle(seeded_session, PASSAGES)
    prepared = oracle.prepare("Хто батьки Аполлона?")
    verdict = '```json\n{"faithful": false, "facts": [true, false], "comment": "вигадка"}\n```'
    judge = FakeListChatModel(responses=[verdict, "не JSON"])
    faithful, coverage, comment = judge_answer(judge, GOLDEN[0], prepared, "Відповідь")
    assert (faithful, coverage, comment) == (False, 0.5, "вигадка")
    faithful, coverage, comment = judge_answer(judge, GOLDEN[0], prepared, "Відповідь")
    assert faithful is None and coverage is None and "no JSON" in comment


def test_cli_eval_writes_report(seeded_default_db: Path, tmp_path: Path):
    from typer.testing import CliRunner

    from delphi.cli import app as cli_app

    out = tmp_path / "report.json"
    res = CliRunner().invoke(cli_app, ["eval", "--type", "negative", "--out", str(out)])
    assert res.exit_code == 0, res.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mode"] == "retrieval"
    assert report["summary"]["усі"]["n"] == len(report["results"]) > 0
    assert all(r["type"] == "negative" for r in report["results"])


def _golden_file(tmp_path: Path) -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text(
        yaml.safe_dump(
            {"questions": [q.model_dump() for q in GOLDEN]}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return path


def test_resume_reuses_partial_results_and_writes_history(
    seeded_default_db: Path, seeded_session: Session, tmp_path: Path
):
    from dataclasses import asdict

    from delphi.eval.run import QuestionResult, run_evaluation

    out = tmp_path / "report.json"
    partial = tmp_path / "report.json.partial.jsonl"
    finished = QuestionResult(
        id="q1", type="factual", question="?", should_refuse=False, rank=99, hit_context=False
    )
    partial.write_text(json.dumps(asdict(finished)) + "\n{torn line", encoding="utf-8")
    history = tmp_path / "history.csv"

    run_evaluation(
        golden_path=_golden_file(tmp_path),
        out=out,
        resume=True,
        oracle=_oracle(seeded_session, PASSAGES),
        history=history,
        note="test",
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in report["results"]}
    assert by_id["q1"]["rank"] == 99  # reused, not recomputed
    assert by_id["q2"]["type"] == "negative"  # the missing one was evaluated
    assert not partial.exists()  # cleaned up after the report is written
    rows = history.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("date,commit,mode,note") and len(rows) == 2
    assert ",test," in rows[1]


def test_partial_results_are_saved_per_question(
    seeded_default_db: Path, seeded_session: Session, tmp_path: Path
):
    from delphi.eval.run import load_partial, run_evaluation

    class PowerCutError(Exception):
        pass

    oracle = _oracle(seeded_session, PASSAGES)
    calls = {"n": 0}
    original = oracle.prepare

    def flaky_prepare(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PowerCutError  # "power cut" on the second question
        return original(*args, **kwargs)

    oracle.prepare = flaky_prepare  # type: ignore[method-assign]
    out = tmp_path / "report.json"
    with pytest.raises(PowerCutError):
        run_evaluation(golden_path=_golden_file(tmp_path), out=out, oracle=oracle)
    saved = load_partial(tmp_path / "report.json.partial.jsonl")
    assert list(saved) == ["q1"] and not out.exists()


def test_resume_requires_out():
    from delphi.eval.run import run_evaluation

    with pytest.raises(ValueError, match="--resume"):
        run_evaluation(resume=True)
