from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 阿里百炼（DashScope OpenAI 兼容模式）
    bailian_api_key: str          # env BAILIAN_API_KEY，必填
    bailian_url: str              # env BAILIAN_URL，必填，完整兼容地址（如 https://dashscope.aliyuncs.com/compatible-mode/v1）
    bailian_model: str = "qwen3.7-max-2026-05-17"  # env BAILIAN_MODEL 可覆盖
    llm_concurrency: int = 4
    chunk_size: int = 4000
    chunk_overlap: int = 400
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str


@lru_cache
def get_settings() -> Settings:
    """全局唯一配置实例（lru_cache 保证只从 .env 加载一次）。"""
    return Settings()
