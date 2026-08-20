from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_concurrency: int = 4
    chunk_size: int = 4000
    chunk_overlap: int = 400
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
