"""OracleService: question -> grounded answer with citations.

Pipeline (architecture doc): condense -> entity linking + expansion -> hybrid retrieve ->
rerank -> prompt -> LLM (streaming) -> post-process citations and entities.

The service does not import Streamlit: the UI streams `stream(prepared)` into st.write_stream
and calls `finalize`; the CLI and a future API simply call `ask`.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from delphi.config import settings
from delphi.ingest.sources import load_sources
from delphi.rag.linker import EntityLinker
from delphi.rag.llm import (
    LLMConfigError,
    LLMUnavailableError,
    describe_llm_error,
    get_chat_model,
)
from delphi.rag.models import Answer, Citation
from delphi.rag.prompts import (
    CONDENSE_QUESTION_PROMPT,
    CONDENSE_QUESTION_PROMPT_EN,
    PYTHIA_SYSTEM_PROMPT,
    PYTHIA_SYSTEM_PROMPT_EN,
    QUERY_TRANSLATION_PROMPT,
    REFUSAL_PHRASE,
    REFUSAL_PHRASE_EN,
    REFUSAL_PHRASES,
    STYLE_IDS,
    STYLES,
    STYLES_EN,
)
from delphi.rag.reranker import Reranker
from delphi.rag.retriever import HybridRetriever, RetrievedPassage

REFUSAL_TEXT = (
    f"{REFUSAL_PHRASE}: джерела мовчать про це. Запитай мене про богів Олімпу, "
    "героїв чи місця античних міфів."
)
REFUSAL_TEXTS = {
    "uk": REFUSAL_TEXT,
    "en": f"{REFUSAL_PHRASE_EN}: the sources are silent on this. Ask me about the gods of "
    "Olympus, the heroes or the places of the ancient myths.",
}


def normalize_style(style: str) -> str:
    """'pythia' / 'scholar' (API) or 'піфія' / 'науковий' -> the internal key."""
    return STYLE_IDS.get(style, style if style in STYLES else "піфія")


_CITATION = re.compile(r"\[(\d+)\]")
_CYRILLIC = re.compile(r"[а-яіїєґ]", re.IGNORECASE)


@dataclass
class PreparedQuestion:
    question: str
    standalone: str
    style: str
    entity_ids: list[str]
    passages: list[RetrievedPassage]
    citations: list[Citation]
    glossary: str
    context: str
    grounded: bool
    notes: list[str] = field(default_factory=list)
    candidates: list[RetrievedPassage] = field(default_factory=list)  # before reranking
    query_en: str | None = None  # English translation used for retrieval
    lang: str = "uk"  # language of the question and of the answer


class OracleService:
    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        reranker: Reranker | None = None,
        linker: EntityLinker | None = None,
        llm: BaseChatModel | None = None,
        llm_factory: Callable[[], BaseChatModel] = get_chat_model,
    ):
        self.retriever = retriever or HybridRetriever(
            k_dense=settings.retrieve_k, k_sparse=settings.retrieve_k
        )
        self._translations: dict[str, str | None] = {}
        self.reranker = reranker or Reranker()
        self.linker = linker or EntityLinker()
        self._llm = llm
        self._llm_factory = llm_factory
        self._source_urls = {s.title: s.url for s in _safe_sources()}

    # ------------------------------------------------------------------ LLM
    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            self._llm = self._llm_factory()  # raises LLMConfigError without an API key
        return self._llm

    def condense(
        self, question: str, history: list[dict[str, str]] | None, lang: str = "uk"
    ) -> str:
        """Rewrite a follow-up ("а хто її мати?") into a standalone question."""
        turns = [h for h in (history or []) if h.get("text")][-settings.history_turns :]
        if not turns:
            return question
        user, pythia = ("User", "Pythia") if lang == "en" else ("Користувач", "Піфія")
        chat_history = "\n".join(
            f"{user if h.get('role') == 'user' else pythia}: {h['text']}" for h in turns
        )
        template = CONDENSE_QUESTION_PROMPT_EN if lang == "en" else CONDENSE_QUESTION_PROMPT
        try:
            chain = ChatPromptTemplate.from_template(template) | self.llm
            result = chain.invoke({"chat_history": chat_history, "question": question})
        except Exception as exc:  # a follow-up is still answerable as asked
            if describe_llm_error(exc) is None:
                raise
            return question
        text = str(result.content).strip()
        return text or question

    def translate(self, question: str) -> str | None:
        """English version of the question for retrieval, or None (disabled / LLM unavailable)."""
        if not settings.query_translation or not question.strip():
            return None
        if question in self._translations:
            return self._translations[question]
        try:
            chain = ChatPromptTemplate.from_template(QUERY_TRANSLATION_PROMPT) | self.llm
            text = str(chain.invoke({"question": question}).content)
        except Exception as exc:  # retrieval still works on the Ukrainian query
            if describe_llm_error(exc) is None:
                raise
            return None
        lines = [line.strip().strip('"').strip() for line in text.strip().splitlines()]
        translation = next((line for line in lines if line), "")
        # a model that answered in Ukrainian instead of translating is no help to BM25
        result = translation if translation and not _CYRILLIC.search(translation) else None
        if len(self._translations) > 1000:
            self._translations.clear()
        self._translations[question] = result
        return result

    # ------------------------------------------------------------------ steps
    def prepare(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        style: str = "піфія",
        lang: str = "uk",
    ) -> PreparedQuestion:
        lang = lang if lang in REFUSAL_PHRASES else "uk"
        style = normalize_style(style)
        standalone = self.condense(question, history, lang)
        entity_ids, expansion = self.linker.extract_and_expand(standalone)
        expansion = self.retriever.known_terms(expansion)
        query = f"{standalone} {' '.join(expansion)}".strip()
        # an English question needs no translation: the corpus is English
        query_en = standalone if lang == "en" else self.translate(standalone)
        candidates = self.retriever.retrieve(
            query=query, boost_entity_ids=entity_ids, top_k=settings.retrieve_k, query_en=query_en
        )
        # the cross-encoder judges English question/English passage pairs far better than
        # Ukrainian/English ones, and only the best few candidates are worth its CPU time
        passages = self.reranker.rerank(
            query_en or standalone,
            candidates[: max(settings.rerank_candidates, settings.context_k)]
            if self.reranker.enabled
            else candidates,
            top_k=settings.context_k,
        )

        citations = [
            Citation(
                num=i,
                work=p.work,
                author=p.author,
                ref=p.ref,
                text_en=p.text,
                translator=p.translator,
                source_url=self._source_urls.get(p.work),
                notes=p.notes,
                entity_ids=p.entity_ids,
            )
            for i, p in enumerate(passages, 1)
        ]
        context = "\n\n".join(f'[{c.num}] {c.ref} — "{c.text_en}"' for c in citations)
        glossary_ids = list(
            dict.fromkeys([*entity_ids, *(e for p in passages for e in p.entity_ids)])
        )
        return PreparedQuestion(
            question=question,
            standalone=standalone,
            style=style,
            entity_ids=entity_ids,
            passages=passages,
            citations=citations,
            glossary=self.linker.get_glossary_for_entities(glossary_ids),
            context=context,
            grounded=bool(passages),
            candidates=candidates,
            query_en=query_en,
            lang=lang,
        )

    def _chain(self, lang: str = "uk"):
        system = PYTHIA_SYSTEM_PROMPT_EN if lang == "en" else PYTHIA_SYSTEM_PROMPT
        prompt = ChatPromptTemplate.from_messages([("system", system), ("human", "{question}")])
        return prompt | self.llm | StrOutputParser()

    def _inputs(self, prepared: PreparedQuestion) -> dict[str, str]:
        styles = STYLES_EN if prepared.lang == "en" else STYLES
        return {
            "style": styles.get(prepared.style, styles["піфія"]),
            "glossary": prepared.glossary,
            "context": prepared.context,
            "question": prepared.standalone,
        }

    def stream(self, prepared: PreparedQuestion) -> Iterator[str]:
        """Token stream of the answer (raises LLMConfigError if the LLM is not configured)."""
        if not prepared.grounded:
            yield REFUSAL_TEXTS[prepared.lang]
            return
        try:
            yield from self._chain(prepared.lang).stream(self._inputs(prepared))
        except LLMConfigError:
            raise
        except Exception as exc:
            reason = describe_llm_error(exc)
            if reason is None:
                raise
            raise LLMUnavailableError(reason) from exc

    def finalize(self, prepared: PreparedQuestion, text: str, error: str | None = None) -> Answer:
        """Validate [n] citations, find mentioned entities, decide whether it is grounded."""
        numbers = [int(n) for n in _CITATION.findall(text)]
        valid = {c.num for c in prepared.citations}
        invalid = sorted({n for n in numbers if n not in valid})
        clean = _CITATION.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", text)
        cited = {n for n in numbers if n in valid}
        citations = [c.model_copy(update={"cited": c.num in cited}) for c in prepared.citations]

        refused = any(phrase.lower() in text.lower() for phrase in REFUSAL_PHRASES.values())
        candidates = [*prepared.entity_ids, *(e for p in prepared.passages for e in p.entity_ids)]
        entities = self.linker.find_in_text(clean, candidates, prepared.lang) if clean else []
        return Answer(
            text=clean.strip(),
            citations=citations,
            entities=entities or prepared.entity_ids,
            grounded=prepared.grounded and not refused and error is None,
            question=prepared.question,
            standalone_question=prepared.standalone,
            invalid_citations=invalid,
            error=error,
            lang=prepared.lang,
            refused=refused or not prepared.grounded,
        )

    # ------------------------------------------------------------------ one-shot
    def ask(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        style: str = "піфія",
        lang: str = "uk",
    ) -> Answer:
        prepared = self.prepare(question, history, style, lang)
        if not prepared.grounded:
            return Answer(
                text=REFUSAL_TEXTS[prepared.lang],
                entities=prepared.entity_ids,
                grounded=False,
                question=question,
                standalone_question=prepared.standalone,
                lang=prepared.lang,
                refused=True,
            )
        try:
            text = self._chain(prepared.lang).invoke(self._inputs(prepared))
        except Exception as exc:
            reason = describe_llm_error(exc)
            if reason is None:
                raise
            return self.finalize(prepared, "", error=reason)
        return self.finalize(prepared, text)


def _safe_sources():
    try:
        return load_sources()
    except FileNotFoundError:
        return []
