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


def test_ollama_model_gets_context_window():
    cfg = Settings(
        _env_file=None, llm_provider="ollama", llm_model="qwen2.5:7b", ollama_num_ctx=8192
    )  # type: ignore[call-arg]
    model = get_chat_model(cfg=cfg)
    assert getattr(model, "num_ctx", None) == 8192


def test_describe_llm_error_for_ollama():
    import httpx

    from delphi.rag.llm import describe_llm_error

    cfg = Settings(_env_file=None, llm_provider="ollama", llm_model="qwen2.5:7b")  # type: ignore[call-arg]
    down = describe_llm_error(httpx.ConnectError("[WinError 10061] connection refused"), cfg)
    assert down and "Ollama не запущена" in down
    missing = describe_llm_error(
        Exception('model "qwen2.5:7b" not found, try pulling it first'), cfg
    )
    assert missing and "ollama pull qwen2.5:7b" in missing
    assert describe_llm_error(ValueError("unrelated bug"), cfg) is None
