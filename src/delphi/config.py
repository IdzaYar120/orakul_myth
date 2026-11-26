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
    # Off by default: +7.5 s per question on CPU. It scores the ENGLISH query against the top
    # `rerank_candidates` passages; below `min_relevance` the oracle refuses before generating
    # (golden set: 5 of 8 traps refused, 3 of 72 answerable questions lost at 0.05).
    rerank_enabled: bool = False
    rerank_candidates: int = 8

    # Retrieval parameters
    retrieve_k: int = 20
    context_k: int = 5
    # Translate the question into English for retrieval (the corpus is English): one short call
    # to the local LLM (~2 s); without the LLM retrieval falls back to the Ukrainian query.
    query_translation: bool = True
    entity_boost: float = 0.5  # soft boost for passages tagged with entities of the question
    min_relevance: float = 0.05  # reranker threshold, tuned on the golden set
    history_turns: int = 6  # chat turns used to condense follow-up questions

    # Public demo protection
    max_question_chars: int = 500
    max_questions_per_session: int = 30

    # HTTP API (`delphi serve`), the backend of the website and the mobile app
    # local  = this process answers (needs Ollama + the search index: the user's PC, a GPU server)
    # remote = forward oracle requests to ORACLE_BACKEND_URL (a public host without the ML stack
    #          reaches the PC through a tunnel); off = encyclopedia and map only
    oracle_mode: Literal["local", "remote", "off"] = "local"
    oracle_backend_url: str | None = None
    # Shared secret between the public API and the oracle backend (header X-Oracle-Token).
    # Set it on any oracle exposed to the internet, so only your public API can use it.
    oracle_token: str | None = None
    oracle_rate_limit: int = 30  # questions per client IP per hour; 0 = unlimited
    oracle_warmup: bool = True  # load the embedding model at startup, not on the 1st question
    api_cors_origins: str = "http://localhost:3000,http://localhost:8081"  # comma-separated

    # Paths
    db_path: Path = Path("delphi.db")
    index_dir: Path = Path("index")
    data_dir: Path = Path("data")


settings = Settings()
