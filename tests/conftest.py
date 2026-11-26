"""Shared pytest fixtures.

Settings are overridden through environment variables (they win over a developer's .env)
*before* any `delphi` module is imported:
- DB_PATH / INDEX_DIR point to a temp dir: tests never touch the real delphi.db or index;
- no model downloads (hashing embedder, reranker off) and no LLM/network calls (empty keys);
- `delphi ingest` never downloads the corpus: every source is read from tests/fixtures/
  (see `offline_sources`), so data/raw/ stays untouched and the tests run without a network.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="delphi-tests-"))
os.environ["DB_PATH"] = str(_TMP / "delphi.db")
os.environ["INDEX_DIR"] = str(_TMP / "index")
os.environ["EMBEDDING_MODEL"] = "hashing"
os.environ["RERANK_ENABLED"] = "false"
os.environ["QUERY_TRANSLATION"] = "false"  # the fake LLMs answer the questions only
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlmodel import Session, create_engine  # noqa: E402

from delphi.db.repo import init_db, seed_database  # noqa: E402
from tests.paths import DATA_DIR  # noqa: E402


@pytest.fixture
def empty_engine(tmp_path: Path) -> Engine:
    eng = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    init_db(engine_override=eng)
    return eng


@pytest.fixture
def seeded_engine(tmp_path: Path) -> Engine:
    eng = create_engine(f"sqlite:///{tmp_path / 'seeded.db'}")
    seed_database(data_dir=DATA_DIR, engine_override=eng)
    return eng


@pytest.fixture
def seeded_session(seeded_engine: Engine) -> Iterator[Session]:
    with Session(seeded_engine) as session:
        yield session


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def offline_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the corpus download with local fixture files for every test."""

    def fixture_file(source, force=False, client=None, filename=None):
        return FIXTURES / (
            "gutenberg.txt" if source.format == "gutenberg_text" else "tei_prose.xml"
        )

    monkeypatch.setattr("delphi.ingest.pipeline.download_source", fixture_file)


@pytest.fixture(scope="session")
def seeded_default_db() -> Path:
    """Seeds the module-level engine (temp DB_PATH) for app/CLI smoke tests."""
    seed_database(data_dir=DATA_DIR)
    return Path(os.environ["DB_PATH"])
