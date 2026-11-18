"""Ingest pipeline on small TEI fixtures: parse -> chunk -> tag -> index -> retrieve."""

from pathlib import Path

import pytest
from sqlmodel import Session, select

from delphi.db.models import Passage, PassageEntity
from delphi.ingest.chunker import chunk_id, chunk_sections, count_tokens
from delphi.ingest.indexer import build_indexes
from delphi.ingest.parsers.tei import ParsedSection, parse_tei_xml
from delphi.ingest.sources import Source, load_sources
from delphi.ingest.tagger import EntityTagger
from delphi.rag.embeddings import HashingEmbedder
from delphi.rag.retriever import HybridRetriever, reciprocal_rank_fusion
from tests.paths import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures"


def _source(prefix: str = "Apollod.", sid: str = "apollodorus_library") -> Source:
    return Source(
        id=sid,
        author="Apollodorus",
        title="Library",
        translator="J. G. Frazer",
        ref_prefix=prefix,
        license="PD",
        url="https://example.org",
        format="tei_xml",
    )


# ---------------------------------------------------------------- parser
def test_tei_prose_sections_and_notes():
    sections = parse_tei_xml(FIXTURES / "tei_prose.xml")
    assert [s.ref for s in sections] == ["1.1.1", "1.1.2", "1.1.3", "1.4.1"]
    first = sections[0]
    assert first.work == "Library" and first.author == "Apollodorus"
    # the note is removed from the text, but the text after it (tail) is kept
    assert "According to Hesiod" not in first.text
    assert first.text.endswith("he begat first the Hundred-handed.")
    assert first.notes == ["According to Hesiod (Hes. Th. 126ff.), Sky was a son of Earth."]
    # page break inside a paragraph does not split words
    assert "Cyclopes. But them Sky bound" in sections[1].text
    assert all(s.kind == "prose" for s in sections)


def test_tei_line_blocks():
    sections = parse_tei_xml(FIXTURES / "tei_lines.xml")
    assert [s.ref for s in sections] == ["116", "120", "123", "126", "453"]
    assert sections[3].notes == ['Or "Sky".']
    assert "And she brought forth long hills." in sections[3].text
    assert all(s.kind == "lines" for s in sections)


def test_repo_sources_are_valid():
    sources = load_sources()
    enabled = [s for s in sources if s.enabled]
    assert {s.id for s in enabled} == {
        "apollodorus_library",
        "hesiod_theogony",
        "hesiod_works_and_days",
    }
    assert all(s.download_url and s.ref_prefix for s in enabled)
    assert all("CC BY-SA" in (s.encoding_license or "") for s in enabled)


# ---------------------------------------------------------------- chunker
def _sec(ref: str, words: int, kind: str = "prose") -> ParsedSection:
    return ParsedSection(work="W", author="A", ref=ref, text="word " * words, kind=kind)


def test_prose_merges_small_sections_and_keeps_ref_range():
    sections = [_sec("1.1.1", 40), _sec("1.1.2", 40), _sec("1.1.3", 200), _sec("1.2.1", 30)]
    chunks = chunk_sections(sections, _source(), min_tokens=150, max_tokens=600)
    assert [c.ref for c in chunks] == ["Apollod. 1.1.1–1.1.3", "Apollod. 1.2.1"]
    assert chunks[0].unit_refs == ["1.1.1", "1.1.2", "1.1.3"]
    assert chunks[0].id == chunk_id("apollodorus_library", "Apollod. 1.1.1–1.1.3")


def test_prose_splits_oversized_section_at_sentences():
    text = " ".join(f"Sentence number {i} tells a long story about gods." for i in range(120))
    section = ParsedSection(work="W", author="A", ref="2.4.1", text=text, notes=["n1"])
    chunks = chunk_sections([section], _source(), max_tokens=300)
    assert len(chunks) > 1
    assert all(c.n_tokens <= 320 for c in chunks)
    assert chunks[0].ref == f"Apollod. 2.4.1 (1/{len(chunks)})"
    assert len({c.id for c in chunks}) == len(chunks)
    assert chunks[0].notes == ["n1"] and chunks[1].notes == []
    assert " ".join(c.text for c in chunks) == text


def test_line_blocks_group_with_overlap():
    blocks = [_sec(str(n), 60, kind="lines") for n in range(1, 60, 5)]
    chunks = chunk_sections(blocks, _source("Hes. Theog.", "hesiod_theogony"), target_tokens=200)
    assert len(chunks) > 1
    assert chunks[0].ref.startswith("Hes. Theog. 1–")
    # one block of overlap between consecutive chunks
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert a.unit_refs[-1] == b.unit_refs[0]
    assert chunks[-1].unit_refs[-1] == "56"


def test_count_tokens_is_monotonic():
    assert count_tokens("one two three") < count_tokens("one two three four five six")


# ---------------------------------------------------------------- tagger
def test_tagger_case_sensitive_and_ambiguous():
    tagger = EntityTagger.from_pairs(
        [
            ("Zeus", "zeus"),
            ("Night", "nyx"),
            ("Earth", "gaia"),
            ("Ajax", "ajax"),
            ("Ajax", "ajax_lesser"),  # ambiguous -> skipped
            ("Ge", "gaia"),  # too short -> skipped
            ("Hera", "hera"),
        ]
    )
    text = "Zeus and black Night; the night was dark. Earth-born Ajax fought. Herald of Hera."
    assert tagger.tag_text(text) == ["hera", "nyx", "zeus"]


def test_tagger_matches_long_names_in_lower_case():
    tagger = EntityTagger.from_pairs([("Hydra", "hydra"), ("Earth", "gaia"), ("Chaos", "chaos")])
    assert tagger.tag_text("he slew the Lernaean hydra") == ["hydra"]
    # common English words keep requiring a capital letter
    assert tagger.tag_text("the earth trembled, all was chaos") == []
    assert tagger.tag_text("Earth bore Chaos") == ["chaos", "gaia"]


# ---------------------------------------------------------------- index + retrieve
@pytest.fixture
def indexed(tmp_path: Path, seeded_session: Session):
    source = _source()
    chunks = chunk_sections(parse_tei_xml(FIXTURES / "tei_prose.xml"), source, min_tokens=20)
    tags = EntityTagger.from_db(seeded_session).tag_chunks(chunks)
    stats = build_indexes(
        chunks, tags, seeded_session, tmp_path, HashingEmbedder(), source_ids={source.id}
    )
    return tmp_path, chunks, tags, stats


def test_index_writes_sqlite_chroma_bm25(indexed, seeded_session: Session):
    index_dir, chunks, tags, stats = indexed
    assert stats.passages == len(chunks) and stats.embedded == len(chunks)
    assert (index_dir / "bm25.pkl").exists() and (index_dir / "chroma").exists()

    passages = seeded_session.exec(select(Passage)).all()
    assert {p.id for p in passages} == {c.id for c in chunks}
    assert all(p.source_id == "apollodorus_library" for p in passages)
    first = next(p for p in passages if p.ref.startswith("Apollod. 1.1.1"))
    assert first.notes and "Hesiod" in first.notes[0]

    tagged = {pe.entity_id for pe in seeded_session.exec(select(PassageEntity)).all()}
    assert {"uranus", "gaia", "cronus", "leto", "apollo"} <= tagged


def test_reindex_is_idempotent(indexed, seeded_session: Session):
    index_dir, chunks, tags, _ = indexed
    again = build_indexes(
        chunks, tags, seeded_session, index_dir, HashingEmbedder(), {"apollodorus_library"}
    )
    assert again.embedded == 0 and again.removed == 0
    # a shorter re-ingest removes stale passages everywhere
    fewer = build_indexes(
        chunks[:1], tags, seeded_session, index_dir, HashingEmbedder(), {"apollodorus_library"}
    )
    assert fewer.removed == len(chunks) - 1
    assert len(seeded_session.exec(select(Passage)).all()) == 1


def test_hybrid_retrieval_with_entity_boost(indexed, seeded_session: Session):
    index_dir, chunks, _, _ = indexed
    retriever = HybridRetriever(
        index_dir=index_dir, embedder=HashingEmbedder(), session=seeded_session
    )
    assert retriever.available
    hits = retriever.retrieve("Latona Delos Artemis Apollo", top_k=3)
    assert hits and hits[0].ref == "Apollod. 1.4.1"
    assert "apollo" in hits[0].entity_ids

    boosted = retriever.retrieve("children", boost_entity_ids=["cronus"], top_k=3)
    assert "cronus" in boosted[0].entity_ids


def test_retriever_without_index_returns_nothing(tmp_path: Path):
    assert HybridRetriever(index_dir=tmp_path / "missing").retrieve("Zeus") == []


def test_reciprocal_rank_fusion():
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]], k=60)
    assert max(scores, key=scores.__getitem__) == "b"
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["d"] == pytest.approx(1 / 63)


# ---------------------------------------------------------------- reference check
def test_ref_containment():
    from delphi.eval.refs import _contains

    assert _contains("Hes. Theog. 116–137", "Hes. Theog. 123")
    assert _contains("Hes. Theog. 116–137", "Hes. Theog. 140")  # last block spans ~5 lines
    assert not _contains("Hes. Theog. 116–137", "Hes. Theog. 160")
    assert _contains("Apollod. 1.1.1–1.1.3", "Apollod. 1.1.2")
    assert _contains("Apollod. 2.4.1 (2/3)", "Apollod. 2.4.1")
    assert not _contains("Apollod. 1.1.1–1.1.3", "Apollod. 1.2.1")
    assert not _contains("Hes. WD 1–20", "Hes. Theog. 5")


def test_check_relation_refs(indexed, seeded_session: Session, tmp_path: Path):
    import yaml

    from delphi.eval.refs import check_relation_refs

    relations = [
        {"src_id": "leto", "rel": "parent_of", "dst_id": "apollo", "source_ref": "Apollod. 1.4.1"},
        {"src_id": "zeus", "rel": "parent_of", "dst_id": "athena", "source_ref": "Apollod. 1.4.1"},
        {"src_id": "zeus", "rel": "parent_of", "dst_id": "hebe", "source_ref": "Apollod. 9.9.9"},
        {"src_id": "zeus", "rel": "spouse_of", "dst_id": "hera", "source_ref": "Wikidata"},
    ]
    path = tmp_path / "relations.yaml"
    path.write_text(yaml.safe_dump(relations), encoding="utf-8")
    statuses = [r.status for r in check_relation_refs(seeded_session, path)]
    assert statuses == ["ok", "entity_missing", "ref_not_found", "not_ingested"]


def test_ref_containment_with_lettered_lines():
    from delphi.eval.refs import _contains

    assert _contains("Hes. Theog. 910–929j", "Hes. Theog. 918")
    assert _contains("Hes. Theog. 929j–950", "Hes. Theog. 938")


def test_tei_note_between_words_does_not_glue_them(tmp_path: Path):
    xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="translation">'
        '<l n="124">of Night were born Aether<note>Or "Ether".</note>and Day, '
        "with her lay the Dark-haired One<note>Poseidon.</note>in a meadow.</l>"
        "</div></body></text></TEI>"
    )
    path = tmp_path / "glue.xml"
    path.write_text(xml, encoding="utf-8")
    section = parse_tei_xml(path)[0]
    assert "Aether and Day" in section.text
    assert "Dark-haired One in a meadow" in section.text
    assert section.notes == ['Or "Ether".', "Poseidon."]
