from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from delphi.config import settings


def get_chat_model(temperature: float = 0.2) -> BaseChatModel:
    """Factory creating an LLM chat instance matching the provider configured in .env."""
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=SecretStr(settings.openai_api_key or "sk-dummy"),
            temperature=temperature,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=settings.llm_model,
            api_key=SecretStr(settings.anthropic_api_key or "dummy"),
            temperature=temperature,
            timeout=60.0,
            stop=None,
        )
    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama

        return cast(
            BaseChatModel,
            ChatOllama(
                base_url=settings.ollama_base_url,
                model=settings.llm_model,
                temperature=temperature,
            ),
        )
    else:
        raise ValueError(f"Невідомий LLM провайдер: {settings.llm_provider}")
