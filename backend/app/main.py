from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.api import characters, health, jobs, novels
from app.config import get_settings
from app.db.neo4j import Neo4jDB
from app.models.job import JobStore
from app.pipeline.llm_client import LLMClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
    except ValidationError as exc:
        raise RuntimeError(
            "配置缺失：请检查 .env（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / NEO4J_PASSWORD 必填）"
        ) from exc
    app.state.settings = settings
    app.state.job_store = JobStore()
    app.state.db = Neo4jDB(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    app.state.llm_client = LLMClient(
        base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model,
    )
    yield
    app.state.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="长篇小说知识图谱分析系统 V0.1", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(novels.router)
    app.include_router(jobs.router)
    app.include_router(characters.router)
    app.include_router(health.router)
    return app


app = create_app()
