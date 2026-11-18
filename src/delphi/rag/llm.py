from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from delphi.config import Settings, settings


class LLMConfigError(ValueError):
    """Raised when the configured LLM provider cannot be created (e.g. missing API key)."""


def get_chat_model(temperature: float = 0.2, cfg: Settings | None = None) -> BaseChatModel:
    """Factory creating an LLM chat instance matching the provider configured in .env."""
    cfg = cfg or settings
    provider = cfg.llm_provider.lower()

    if provider == "openai":
        if not cfg.openai_api_key:
            raise LLMConfigError("OPENAI_API_KEY не задано в .env (LLM_PROVIDER=openai).")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.llm_model,
            api_key=SecretStr(cfg.openai_api_key),
            temperature=temperature,
        )
    elif provider == "anthropic":
        if not cfg.anthropic_api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY не задано в .env (LLM_PROVIDER=anthropic).")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=cfg.llm_model,
            api_key=SecretStr(cfg.anthropic_api_key),
            temperature=temperature,
            timeout=60.0,
            stop=None,
        )
    elif provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            base_url=cfg.ollama_base_url,
            model=cfg.llm_model,
            temperature=temperature,
        )
    else:
        raise LLMConfigError(f"Невідомий LLM провайдер: {cfg.llm_provider}")
