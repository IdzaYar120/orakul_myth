import pytest
from sqlmodel import Session

from delphi.rag.linker import EntityLinker
from delphi.rag.oracle import OracleService
from delphi.rag.reranker import Reranker
from delphi.rag.retriever import HybridRetriever, RetrievedPassage


class FakeRetriever(HybridRetriever):
    def __init__(self, passages: list[RetrievedPassage]):
        super().__init__()
        self._passages = passages
        self.last_query: str | None = None
        self.last_boost: list[str] | None = None

    def retrieve(self, query, boost_entity_ids=None, top_k=10):
        self.last_query = query
        self.last_boost = boost_entity_ids
        return self._passages[:top_k]


@pytest.mark.parametrize("question", ["Хто виховував Ахілла?", "Хто вчив Ахіллеса?"])
def test_linker_resolves_ukrainian_inflections(seeded_session: Session, question: str):
    ids, expansion = EntityLinker(session=seeded_session).extract_and_expand(question)
    assert ids == ["achilles"]
    assert "Achilles" in expansion


def test_oracle_refusal_when_no_passages(seeded_session: Session):
    oracle = OracleService(
        retriever=FakeRetriever([]),
        reranker=Reranker(),
        linker=EntityLinker(session=seeded_session),
    )
    answer = oracle.ask("Який номер телефону в Зевса?")
    assert answer.grounded is False
    assert answer.citations == []
    assert "Дим над священним триножником розвіявся" in answer.text
    assert "zeus" in answer.entities


def test_oracle_grounded_answer_has_citations(seeded_session: Session):
    passage = RetrievedPassage(
        id="p1",
        work="Theogony",
        author="Hesiod",
        translator="H. G. Evelyn-White",
        ref="918",
        text="And Leto was joined in love with Zeus...",
        entity_ids=["zeus", "apollo"],
    )
    retriever = FakeRetriever([passage])
    oracle = OracleService(
        retriever=retriever,
        reranker=Reranker(),
        linker=EntityLinker(session=seeded_session),
    )
    answer = oracle.ask("Хто батько Аполлона?")

    assert answer.grounded is True
    assert [c.ref for c in answer.citations] == ["918"]
    assert "[1]" in answer.text
    # Query expanded with English aliases and boosted by linked entity
    assert retriever.last_query is not None and "Apollo" in retriever.last_query
    assert retriever.last_boost == ["apollo"]
