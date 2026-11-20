from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from delphi.config import Settings, settings


class LLMConfigError(ValueError):
    """The configured LLM provider cannot be used (missing API key, unknown provider)."""


class LLMUnavailableError(LLMConfigError):
    """The LLM is configured but not reachable (Ollama not running, model not pulled)."""


def get_chat_model(temperature: float | None = None, cfg: Settings | None = None) -> BaseChatModel:
    """Factory creating an LLM chat instance matching the provider configured in .env."""
    cfg = cfg or settings
    provider = cfg.llm_provider.lower()
    temp = cfg.llm_temperature if temperature is None else temperature

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            base_url=cfg.ollama_base_url,
            model=cfg.llm_model,
            temperature=temp,
            num_ctx=cfg.ollama_num_ctx,
            keep_alive=cfg.ollama_keep_alive,
        )
    elif provider == "openai":
        if not cfg.openai_api_key:
            raise LLMConfigError("OPENAI_API_KEY не задано в .env (LLM_PROVIDER=openai).")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.llm_model,
            api_key=SecretStr(cfg.openai_api_key),
            temperature=temp,
        )
    elif provider == "anthropic":
        if not cfg.anthropic_api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY не задано в .env (LLM_PROVIDER=anthropic).")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=cfg.llm_model,
            api_key=SecretStr(cfg.anthropic_api_key),
            temperature=temp,
            timeout=60.0,
            stop=None,
        )
    else:
        raise LLMConfigError(f"Невідомий LLM провайдер: {cfg.llm_provider}")


def describe_llm_error(exc: BaseException, cfg: Settings | None = None) -> str | None:
    """Human-readable reason when the LLM call failed for an operational reason, else None."""
    cfg = cfg or settings
    if isinstance(exc, LLMConfigError):
        return str(exc)
    text = f"{type(exc).__name__}: {exc}".lower()
    if cfg.llm_provider == "ollama":
        if "connect" in text or "connection refused" in text or "failed to establish" in text:
            return (
                f"Ollama не запущена ({cfg.ollama_base_url}). Запустіть застосунок Ollama "
                "або `ollama serve`."
            )
        if "not found" in text and ("model" in text or "pull" in text):
            return (
                f"Модель «{cfg.llm_model}» не завантажена: виконайте `ollama pull {cfg.llm_model}`."
            )
    elif "connect" in text or "timeout" in text:
        return f"LLM-провайдер {cfg.llm_provider} недоступний: {exc}"
    return None
