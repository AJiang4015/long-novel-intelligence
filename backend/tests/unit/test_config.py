import pytest
from pydantic import ValidationError

from app.config import Settings

BAILIAN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-test")
    monkeypatch.setenv("BAILIAN_URL", BAILIAN_URL)
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    s = Settings(_env_file=None)
    assert s.bailian_api_key == "sk-test"
    assert s.bailian_url == BAILIAN_URL
    assert s.bailian_model == "qwen3.7-max-2026-05-17"  # 默认模型
    assert s.llm_concurrency == 4      # 默认值
    assert s.chunk_size == 4000        # 默认值
    assert s.neo4j_uri == "bolt://localhost:7687"


def test_settings_model_overridable(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-test")
    monkeypatch.setenv("BAILIAN_URL", BAILIAN_URL)
    monkeypatch.setenv("BAILIAN_MODEL", "qwen-max")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    s = Settings(_env_file=None)
    assert s.bailian_model == "qwen-max"


def test_settings_requires_bailian_key(monkeypatch):
    monkeypatch.delenv("BAILIAN_API_KEY", raising=False)
    monkeypatch.setenv("BAILIAN_URL", BAILIAN_URL)
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_requires_bailian_url(monkeypatch):
    monkeypatch.delenv("BAILIAN_URL", raising=False)
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-test")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
