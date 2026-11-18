from delphi.config import Settings


def test_default_config():
    cfg = Settings()
    assert cfg.llm_provider in ["openai", "anthropic", "ollama"]
    assert cfg.retrieve_k > 0
    assert cfg.context_k > 0
    assert cfg.min_relevance >= 0.0
