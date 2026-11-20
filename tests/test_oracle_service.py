import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlmodel import Session

from delphi.rag.linker import EntityLinker
from delphi.rag.llm import LLMConfigError
from delphi.rag.oracle import REFUSAL_TEXT, OracleService
from delphi.rag.prompts import REFUSAL_PHRASE
from delphi.rag.reranker import Reranker
from delphi.rag.retriever import HybridRetriever, RetrievedPassage

PASSAGES = [
    RetrievedPassage(
        id="p1",
        work="Theogony",
        author="Hesiod",
        translator="H. G. Evelyn-White",
        ref="Hes. Theog. 912–929",
        text="And Leto was joined in love with Zeus and bare Apollo and Artemis.",
        entity_ids=["apollo", "artemis", "leto", "zeus"],
    ),
    RetrievedPassage(
        id="p2",
        work="Library",
        author="Apollodorus",
        translator="J. G. Frazer",
        ref="Apollod. 1.4.1",
        text="Latona came to Delos and brought forth first Artemis, then Apollo.",
        entity_ids=["apollo", "artemis", "delos", "leto"],
    ),
]


class FakeRetriever(HybridRetriever):
    def __init__(self, passages: list[RetrievedPassage]):
        super().__init__()
        self._passages = passages
        self.last_query: str | None = None
        self.last_boost: list[str] | None = None

    def retrieve(self, query, boost_entity_ids=None, top_k=10):
        self.last_query = query
        self.last_boost = list(boost_entity_ids or [])
        return self._passages[:top_k]


def _no_llm():
    raise LLMConfigError("OPENAI_API_KEY не задано в .env (LLM_PROVIDER=openai).")


def _oracle(session: Session, passages, responses=None, llm_factory=None) -> OracleService:
    return OracleService(
        retriever=FakeRetriever(passages),
        reranker=Reranker(enabled=False),
        linker=EntityLinker(session=session),
        llm=FakeListChatModel(responses=responses) if responses else None,
        llm_factory=llm_factory or _no_llm,
    )


@pytest.mark.parametrize("question", ["Хто виховував Ахілла?", "Хто вчив Ахіллеса?"])
def test_linker_resolves_ukrainian_inflections(seeded_session: Session, question: str):
    ids, expansion = EntityLinker(session=seeded_session).extract_and_expand(question)
    assert ids == ["achilles"]
    assert expansion[0] == "Achilles" and len(expansion) <= 4


def test_linker_finds_entities_in_answer(seeded_session: Session):
    linker = EntityLinker(session=seeded_session)
    text = "Лето народила Аполлона та Артеміду на Делосі від Зевса."
    found = linker.find_in_text(text, ["apollo", "artemis", "delos", "zeus", "hera"])
    assert found == ["apollo", "artemis", "delos", "zeus"]


def test_refusal_when_no_passages(seeded_session: Session):
    answer = _oracle(seeded_session, []).ask("Який номер телефону в Зевса?")
    assert answer.grounded is False
    assert answer.citations == []
    assert answer.text == REFUSAL_TEXT and REFUSAL_PHRASE in answer.text
    assert "zeus" in answer.entities


def test_grounded_answer_with_citations(seeded_session: Session):
    oracle = _oracle(
        seeded_session,
        PASSAGES,
        responses=["Батьки Аполлона — Зевс і Лето [1]; народився він на Делосі [2] [7]."],
    )
    answer = oracle.ask("Хто батьки Аполлона?", style="науковий")

    assert answer.grounded and answer.error is None
    assert [c.ref for c in answer.citations] == ["Hes. Theog. 912–929", "Apollod. 1.4.1"]
    assert [c.cited for c in answer.citations] == [True, True]
    assert answer.invalid_citations == [7]
    assert "[7]" not in answer.text and "[1]" in answer.text
    assert {"apollo", "zeus", "leto", "delos"} <= set(answer.entities)
    # query expansion with English names and entity boost
    retriever = oracle.retriever
    assert isinstance(retriever, FakeRetriever)
    assert retriever.last_query is not None and "Apollo" in retriever.last_query
    assert retriever.last_boost == ["apollo"]


def test_model_refusal_is_not_grounded(seeded_session: Session):
    oracle = _oracle(seeded_session, PASSAGES, responses=[f"{REFUSAL_PHRASE}. Спитай про Лето."])
    assert oracle.ask("Що їв Аполлон на сніданок?").grounded is False


def test_missing_llm_key_still_returns_sources(seeded_session: Session):
    answer = _oracle(seeded_session, PASSAGES).ask("Хто батьки Аполлона?")
    assert answer.error and "OPENAI_API_KEY" in answer.error
    assert len(answer.citations) == 2 and answer.grounded is False


def test_follow_up_question_is_condensed(seeded_session: Session):
    oracle = _oracle(
        seeded_session,
        PASSAGES,
        responses=["Хто мати Аполлона?", "Мати Аполлона — Лето [1]."],
    )
    history = [
        {"role": "user", "text": "Розкажи про Аполлона"},
        {"role": "assistant", "text": "Аполлон — бог світла [1]."},
    ]
    answer = oracle.ask("а хто його мати?", history=history)
    assert answer.standalone_question == "Хто мати Аполлона?"
    assert "Лето" in answer.text


def test_streaming_matches_finalize(seeded_session: Session):
    oracle = _oracle(seeded_session, PASSAGES, responses=["Зевс і Лето [1]."])
    prepared = oracle.prepare("Хто батьки Аполлона?")
    text = "".join(oracle.stream(prepared))
    answer = oracle.finalize(prepared, text)
    assert answer.text == "Зевс і Лето [1]." and answer.citations[0].cited


class _DownLLM(FakeListChatModel):
    def _call(self, *args, **kwargs):  # type: ignore[override]
        import httpx

        raise httpx.ConnectError("connection refused")

    def _stream(self, *args, **kwargs):  # type: ignore[override]
        import httpx

        raise httpx.ConnectError("connection refused")


def test_ollama_down_returns_sources_with_reason(seeded_session: Session, monkeypatch):
    from delphi.config import settings
    from delphi.rag.llm import LLMUnavailableError

    monkeypatch.setattr(settings, "llm_provider", "ollama")
    oracle = OracleService(
        retriever=FakeRetriever(PASSAGES),
        reranker=Reranker(enabled=False),
        linker=EntityLinker(session=seeded_session),
        llm=_DownLLM(responses=["unused"]),
    )
    answer = oracle.ask("Хто батьки Аполлона?")
    assert answer.error and "Ollama не запущена" in answer.error
    assert len(answer.citations) == 2

    prepared = oracle.prepare("Хто батьки Аполлона?")
    with pytest.raises(LLMUnavailableError):
        "".join(oracle.stream(prepared))
