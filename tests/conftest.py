"""Shared pytest fixtures.

DB_PATH / INDEX_DIR are redirected to a temp dir *before* any `delphi` module is
imported, so tests never read or create the developer's real `delphi.db`.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="delphi-tests-"))
os.environ["DB_PATH"] = str(_TMP / "delphi.db")
os.environ["INDEX_DIR"] = str(_TMP / "index")

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


@pytest.fixture(scope="session")
def seeded_default_db() -> Path:
    """Seeds the module-level engine (temp DB_PATH) for app/CLI smoke tests."""
    seed_database(data_dir=DATA_DIR)
    return Path(os.environ["DB_PATH"])
