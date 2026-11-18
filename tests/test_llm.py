import pytest

from delphi.config import Settings
from delphi.rag.llm import LLMConfigError, get_chat_model


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_missing_api_key_raises(provider: str):
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_provider=provider,
        openai_api_key=None,
        anthropic_api_key=None,
    )
    with pytest.raises(LLMConfigError):
        get_chat_model(cfg=cfg)


def test_ollama_needs_no_key():
    cfg = Settings(_env_file=None, llm_provider="ollama", llm_model="llama3.1")  # type: ignore[call-arg]
    model = get_chat_model(cfg=cfg)
    assert type(model).__name__ == "ChatOllama"


def test_openai_with_key():
    cfg = Settings(_env_file=None, llm_provider="openai", openai_api_key="sk-test")  # type: ignore[call-arg]
    model = get_chat_model(cfg=cfg)
    assert type(model).__name__ == "ChatOpenAI"
