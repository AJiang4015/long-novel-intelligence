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
    merge_confidence_threshold: float = 0.5   # V0.2.3-b：canonical merge 置信度阈值（可配置）

    # ---- V0.2.7 Task A：P06 lineage 观测（默认全关；关闭时 recorder 为 no-op，零开销）----
    er_lineage: bool = False                   # env ER_LINEAGE：mention lineage 总开关（默认 off）
    er_lineage_dir: str = "lineage"            # env ER_LINEAGE_DIR：lineage JSONL 输出目录（相对 backend cwd）
    er_lineage_raw_extraction: bool = False    # env ER_LINEAGE_RAW_EXTRACTION：原始 extraction 三元组 dump
                                               # （debug 能力，默认 off；深挖 extraction 时显式开启）

    # ---- P19：resumable analysis checkpoint（默认开；False = 完全回退现状，不写不查）----
    er_checkpoint_dir: str = "checkpoints"     # env ER_CHECKPOINT_DIR：checkpoint 根目录（相对 backend cwd）
    er_checkpoint_enabled: bool = True         # env ER_CHECKPOINT_ENABLED：checkpoint/resume 总开关


@lru_cache
def get_settings() -> Settings:
    """全局唯一配置实例（lru_cache 保证只从 .env 加载一次）。"""
    return Settings()
