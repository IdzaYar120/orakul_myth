from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Settings: a local model via Ollama by default (no external API, no key)
    llm_provider: Literal["openai", "anthropic", "ollama"] = "ollama"
    llm_model: str = "hf.co/INSAIT-Institute/MamayLM-Gemma-3-12B-IT-v1.0-GGUF:Q4_K_M"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    # Ollama's default context (2048 tokens) is too small for 5 passages + the prompt
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"  # keep the model in (GPU) memory between questions
    llm_temperature: float = 0.2

    # Embeddings & Reranker
    embedding_model: str = "BAAI/bge-m3"  # "hashing" = no-model stand-in (tests/CI)
    embedding_device: str | None = None  # None = auto (cuda if available), or "cpu"
    embedding_batch_size: int = 16
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = False

    # Retrieval parameters
    retrieve_k: int = 20
    context_k: int = 5
    # Translate the question into English for retrieval (the corpus is English): one short call
    # to the local LLM (~2 s); without the LLM retrieval falls back to the Ukrainian query.
    query_translation: bool = True
    entity_boost: float = 0.5  # soft boost for passages tagged with entities of the question
    min_relevance: float = 0.3
    history_turns: int = 6  # chat turns used to condense follow-up questions

    # Public demo protection
    max_question_chars: int = 500
    max_questions_per_session: int = 30

    # Paths
    db_path: Path = Path("delphi.db")
    index_dir: Path = Path("index")
    data_dir: Path = Path("data")


settings = Settings()
