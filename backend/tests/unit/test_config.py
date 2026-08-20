import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    s = Settings(_env_file=None)
    assert s.llm_base_url == "https://example.com/v1"
    assert s.llm_model == "test-model"
    assert s.llm_concurrency == 4      # 默认值
    assert s.chunk_size == 4000        # 默认值
    assert s.neo4j_uri == "bolt://localhost:7687"


def test_settings_requires_llm_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
