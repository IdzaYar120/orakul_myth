"""Shared helpers for SQLite-backed services."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlmodel import Session

from delphi.db.models import Entity
from delphi.db.repo import engine
from delphi.encyclopedia.models import EntityRef


class SessionMixin:
    """Use an injected session (tests, request scope) or open a short-lived one."""

    def __init__(self, session: Session | None = None):
        self._session = session

    @contextmanager
    def _use_session(self, session: Session | None = None) -> Generator[Session]:
        if session is not None:
            yield session
        elif self._session is not None:
            yield self._session
        else:
            with Session(engine) as sess:
                yield sess


def entity_ref(e: Entity) -> EntityRef:
    return EntityRef(
        id=e.id, type=e.type, name_uk=e.name_uk, name_en=e.name_en, summary_uk=e.summary_uk
    )
