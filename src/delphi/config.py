from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Settings
    llm_provider: Literal["openai", "anthropic", "ollama"] = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # Embeddings & Reranker
    embedding_model: str = "BAAI/bge-m3"  # "hashing" = no-model stand-in (tests/CI)
    embedding_device: str | None = None  # None = auto (cuda if available), or "cpu"
    embedding_batch_size: int = 16
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = False

    # Retrieval parameters
    retrieve_k: int = 20
    context_k: int = 5
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
