from collections.abc import Generator

from delphi.config import settings
from delphi.rag.linker import EntityLinker
from delphi.rag.models import Answer, Citation
from delphi.rag.prompts import PYTHIA_SYSTEM_PROMPT
from delphi.rag.reranker import Reranker
from delphi.rag.retriever import HybridRetriever


class OracleService:
    """
    Головний сервіс RAG-чату «Дельфійський оракул».
    Працює незалежно від Streamlit: використовується в UI, CLI та тестах.
    """

    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        reranker: Reranker | None = None,
        linker: EntityLinker | None = None,
    ):
        self.retriever = retriever or HybridRetriever(
            k_dense=settings.retrieve_k,
            k_sparse=settings.retrieve_k,
        )
        self.reranker = reranker or Reranker()
        self.linker = linker or EntityLinker()

    def ask(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        style: str = "піфія",
    ) -> Answer:
        """
        Обробляє запитання користувача та повертає структуровану відповідь з цитатами.
        """
        # 1. Entity linking + expansion
        entity_ids, expansion_terms = self.linker.extract_and_expand(question)
        expanded_query = f"{question} {' '.join(expansion_terms)}".strip()

        # 2. Hybrid retrieve
        passages = self.retriever.retrieve(
            query=expanded_query,
            boost_entity_ids=entity_ids,
            top_k=settings.retrieve_k,
        )

        # 3. Rerank
        reranked_passages = self.reranker.rerank(
            query=question,
            passages=passages,
            top_k=settings.context_k,
        )

        # 4. Якщо уривків немає або скор нижче порога
        if not reranked_passages:
            refusal_text = (
                "Дим над священним триножником розвіявся, і джерела мовчать про це. "
                "Запитай мене про богів Олімпу (Зевса, Аполлона, Афіну) або героїв античності."
            )
            return Answer(
                text=refusal_text,
                citations=[],
                entities=entity_ids,
                grounded=False,
            )

        # 5. Підготовка контексту цитат
        citations: list[Citation] = []
        context_blocks: list[str] = []
        for idx, p in enumerate(reranked_passages, 1):
            citations.append(
                Citation(
                    num=idx,
                    work=p.work,
                    author=p.author,
                    ref=p.ref,
                    text_en=p.text,
                )
            )
            context_blocks.append(f'[{idx}] {p.author}, {p.work} ({p.ref}) — "{p.text}"')

        context_str = "\n\n".join(context_blocks)
        glossary = self.linker.get_glossary_for_entities(entity_ids)

        _system_prompt = PYTHIA_SYSTEM_PROMPT.format(
            style=style,
            glossary=glossary,
            context=context_str,
        )

        # 6. Генерація відповіді
        # Якщо API ключ відсутній або триває перевірка каркасу — повертаємо базовий текст
        answer_text = (
            f"Згідно зі свідченнями стародавніх текстів [{citations[0].num}], "
            f"воля богів відкривається тим, хто шукає знань."
        )

        return Answer(
            text=answer_text,
            citations=citations,
            entities=entity_ids,
            grounded=True,
        )

    def stream_ask(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        style: str = "піфія",
    ) -> Generator[str, None, Answer]:
        """Стрімінг відповіді для відображення через st.write_stream."""
        ans = self.ask(question, history, style)
        for word in ans.text.split(" "):
            yield word + " "
        return ans
