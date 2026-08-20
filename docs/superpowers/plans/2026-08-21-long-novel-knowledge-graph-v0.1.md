# 长篇小说知识图谱分析系统 V0.1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 V0.1：上传 EPUB 小说 → 用户选择人物 → 返回该人物 1 跳关系网络图。

**Architecture:** 单进程 FastAPI 后端 + Neo4j（Docker）图存储 + React 前端。抽取管线为「EPUB→章节→切块→并发 LLM 强制结构化抽取→Pydantic 校验→merger 聚合→写 Neo4j」；任务状态存进程内字典，前端 1s 轮询进度；查询时 novel_id + character_id 双层隔离。

**Tech Stack:** Python 3.11+ / FastAPI / pydantic v2 / pydantic-settings / ebooklib / httpx / neo4j 5.x driver；Neo4j Community 5.x（Docker Compose）；React + Vite + TypeScript + react-force-graph-2d。

## Global Constraints

- Python ≥ 3.11；Neo4j Community 5.x（docker-compose，镜像 `neo4j:5.26-community`）
- **所有 Neo4j 查询必须带 novel_id**；关系查询采用 novel_id + character_id 双层隔离
- **Job 状态枚举固定**：`pending | running | completed | completed_with_errors | failed`
  - `completed`：所有 chunk 成功；`completed_with_errors`：至少一个 chunk 失败但图谱生成成功；`failed`：全部 chunk 失败或致命错误（EPUB 解析/Neo4j）
- **weight = 确认该关系的不同 chunk 数**（块内重复输出只计一次）；**confidence = 各确认 chunk 的算术平均**（不加权）；**evidence 按首次发现顺序保留前 5 条**（第 6 条起不再追加，weight/chunk_ids 照常累加）
- **LLM 并发数来自配置**（`LLM_CONCURRENCY` 默认 4），代码中禁止写死并发数
- **Chunk offset 为相对该章节纯文本的字符偏移**（非整本偏移）
- Chunk 内部结构固定：`Chunk(chunk_id, chapter_id, chapter_title, text, start_offset, end_offset)`
- LLM 输出强制结构化：`response_format={"type": "json_object"}` + Pydantic 严格校验（长度 1–50、confidence 0–1、type 仅 7 枚举、self-loop 丢弃）；禁止正则解析
- 失败分类：429/5xx → 重试 1 次；Pydantic validation error → 不重试；失败块记 `{chunk_id, chapter_id, error}`，LLM 原始输出只进服务端日志
- type 枚举仅：`love / family / friendship / enmity / alliance / mentorship / other`
- schemas 拆分：`schemas/llm.py`（LLM 输出契约）+ `schemas/api.py`（HTTP）；`models/job.py` 为内部 Pydantic 任务状态模型，**禁止引入 ORM**
- 前端薄转换层：后端 DTO 与 force-graph 内部状态隔离（`types.ts` 中 `toForceGraph`）
- 默认 `pytest` 只跑单元测试；集成测试需 `pytest -m integration`（要求 Neo4j 运行中）
- README 必须声明：Job state is process-local in V0.1 and will be replaced by a persistent task store in later versions

## File Structure

```
Long-Novel-Intelligence/
├── docker-compose.yml                  # Task 1
├── .env.example                        # Task 1
├── .gitignore                          # Task 1
├── README.md                           # Task 1（Task 14 完善）
├── backend/
│   ├── pyproject.toml                  # Task 1
│   ├── app/
│   │   ├── __init__.py                 # Task 1
│   │   ├── main.py                     # Task 10
│   │   ├── config.py                   # Task 2
│   │   ├── api/__init__.py             # Task 1
│   │   ├── api/novels.py               # Task 10（含 _run_ingest 编排）
│   │   ├── api/jobs.py                 # Task 10
│   │   ├── api/characters.py           # Task 10
│   │   ├── api/health.py               # Task 10
│   │   ├── pipeline/__init__.py        # Task 1
│   │   ├── pipeline/epub_reader.py     # Task 4
│   │   ├── pipeline/chunker.py         # Task 5
│   │   ├── pipeline/llm_client.py      # Task 7
│   │   ├── pipeline/extractor.py       # Task 7
│   │   ├── pipeline/merger.py          # Task 6
│   │   ├── db/__init__.py              # Task 1
│   │   ├── db/neo4j.py                 # Task 9
│   │   ├── schemas/__init__.py         # Task 1
│   │   ├── schemas/llm.py              # Task 3
│   │   ├── schemas/api.py              # Task 10
│   │   └── models/__init__.py          # Task 1
│   │   └── models/job.py               # Task 8
│   └── tests/
│       ├── conftest.py                 # Task 1（marker 注册 + integration 默认排除）
│       ├── epub_factory.py             # Task 4（测试用 EPUB 构造 helper，unit/integration 共用）
│       ├── unit/
│       │   ├── test_config.py          # Task 2
│       │   ├── test_chunker.py         # Task 4 + Task 5
│       │   ├── test_merger.py          # Task 6
│       │   ├── test_llm_client.py      # Task 3 + Task 7
│       │   └── test_job_store.py       # Task 8
│       └── integration/
│           └── test_api_neo4j.py       # Task 9 + Task 10
└── frontend/
    ├── package.json                    # Task 11
    ├── vite.config.ts                  # Task 11
    └── src/
        ├── main.tsx / App.tsx          # Task 11 / Task 12
        ├── api.ts                      # Task 11
        ├── types.ts                    # Task 11
        └── components/
            ├── Upload.tsx              # Task 12
            ├── Progress.tsx            # Task 12
            ├── CharacterSearch.tsx     # Task 13
            └── GraphView.tsx           # Task 13
```

> 对 spec 目录树的两处补充（不违背 unit/integration 拆分原则）：`tests/epub_factory.py`（测试 EPUB 构造 helper，避免 unit/integration 重复代码）、`tests/unit/test_config.py`（配置校验测试）、`tests/unit/test_job_store.py`（JobStore 状态机与并发测试）。

---

### Task 1: 工程骨架 + Neo4j Docker

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `README.md`
- Create: `backend/pyproject.toml`
- Create: `backend/tests/conftest.py`
- Create: `backend/app/__init__.py`、`backend/app/api/__init__.py`、`backend/app/pipeline/__init__.py`、`backend/app/db/__init__.py`、`backend/app/schemas/__init__.py`、`backend/app/models/__init__.py`（均为空文件）

**Interfaces:**
- Consumes: 无
- Produces: docker-compose 提供 Neo4j（`bolt://localhost:7687`，账号 `neo4j` / 密码 `noveldev2026`）；pyproject 定义后端依赖与 pytest marker；conftest 保证默认 `pytest` 排除 integration 用例

- [ ] **Step 1: 写 docker-compose.yml**

```yaml
services:
  neo4j:
    image: neo4j:5.26-community
    container_name: novel-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/noveldev2026
    volumes:
      - neo4j_data:/data

volumes:
  neo4j_data:
```

- [ ] **Step 2: 写 .env.example**

```
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxx
LLM_MODEL=deepseek-chat
LLM_CONCURRENCY=4
CHUNK_SIZE=4000
CHUNK_OVERLAP=400
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=noveldev2026
```

- [ ] **Step 3: 写 .gitignore**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
.env
node_modules/
dist/
```

- [ ] **Step 4: 写 backend/pyproject.toml**

```toml
[project]
name = "novel-kg-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "neo4j>=5.20",
    "ebooklib>=0.18",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
markers = [
    "integration: requires a running Neo4j (docker compose up -d neo4j)",
]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 5: 写 backend/tests/conftest.py**

```python
import pytest


def pytest_collection_modifyitems(config, items):
    """默认排除 integration 用例；显式 `pytest -m integration` 时才运行。"""
    marker_expr = config.getoption("markexpr") or ""
    if "integration" in marker_expr:
        return
    items[:] = [item for item in items if "integration" not in item.keywords]
```

- [ ] **Step 6: 写 README.md（骨架，Task 14 完善）**

```markdown
# 长篇小说知识图谱分析系统 V0.1

上传 EPUB 小说 → 选择人物 → 查看该人物的 1 跳人物关系网络。

## 启动

1. `cp .env.example .env`，填写 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`；如修改了 Neo4j 密码需同步 `.env`
2. `docker compose up -d neo4j`
3. 后端：`cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload --port 8000`
4. 前端：`cd frontend && npm install && npm run dev`（访问 http://localhost:5173）

## 测试

- 单元测试（无需 Neo4j / 真实 LLM）：`cd backend && pytest`
- 集成测试（需 Neo4j 运行中）：`cd backend && pytest -m integration`

## V0.1 已知限制

> **Job state is process-local in V0.1 and will be replaced by a persistent task store in later versions.**

- 人物不做别名归并：LLM 输出的不同写法视为不同 Person
- 关系为有向边，方向仅表示抽取时的主体 → 客体
- weight = 确认该关系的不同 chunk 数；confidence = 各确认 chunk confidence 的算术平均
```

- [ ] **Step 7: 创建空 `__init__.py` 并启动 Neo4j**

```powershell
# 在 backend/app 及其子目录 api/pipeline/db/schemas/models 下各建一个空 __init__.py
cd E:\CodeField\Long-Novel-Intelligence
docker compose up -d neo4j
```

- [ ] **Step 8: 验证**

```powershell
docker compose ps                      # 期望 neo4j 状态为 running/healthy
cd backend
pip install -e ".[dev]"                # 期望安装成功
pytest                                 # 期望 0 tests collected, exit code 0
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: V0.1 工程骨架（docker-compose/配置/后端依赖/测试骨架）"
```

---

### Task 2: config.py（配置加载与启动校验）

**Files:**
- Create: `backend/app/config.py`
- Test: `backend/tests/unit/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `get_settings() -> Settings`（lru_cache 单例）；`Settings` 字段：`llm_base_url: str`、`llm_api_key: str`、`llm_model: str`、`llm_concurrency: int = 4`、`chunk_size: int = 4000`、`chunk_overlap: int = 400`、`neo4j_uri: str = "bolt://localhost:7687"`、`neo4j_user: str = "neo4j"`、`neo4j_password: str`。缺失必填项（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL/NEO4J_PASSWORD）时 `Settings()` 抛 `pydantic.ValidationError`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_config.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.config'`）

- [ ] **Step 3: 写 config.py**

```python
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
```

> 说明：不在模块导入时实例化 `Settings()`，避免单元测试环境缺少 .env 时导入即崩；必填字段缺失由 pydantic-settings 抛 `ValidationError`，由 main.py 启动时捕获并给出友好提示（Task 10）。

- [ ] **Step 4: 运行确认通过**

```powershell
pytest tests/unit/test_config.py -v
```

期望：2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/unit/test_config.py
git commit -m "feat: 配置加载与启动校验（pydantic-settings）"
```

---

### Task 3: schemas/llm.py（LLM 输出契约）

**Files:**
- Create: `backend/app/schemas/llm.py`
- Test: `backend/tests/unit/test_llm_client.py`（第一部分：契约校验）

**Interfaces:**
- Consumes: 无
- Produces: `RelationshipType`（str Enum，7 值）、`Character(name: str)`、`Relationship(source, target, type, confidence)`、`ExtractionResult(characters, relationships)`——self-loop 在 `ExtractionResult` 校验时被过滤

- [ ] **Step 1: 写失败测试**

```python
import pytest
from pydantic import ValidationError

from app.schemas.llm import ExtractionResult, RelationshipType


def test_extraction_result_valid():
    result = ExtractionResult.model_validate({
        "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}],
        "relationships": [
            {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.95},
        ],
    })
    assert result.relationships[0].type == RelationshipType.love


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({
            "characters": [],
            "relationships": [
                {"source": "贾宝玉", "target": "林黛玉", "type": "romantic", "confidence": 0.9},
            ],
        })


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({
            "characters": [],
            "relationships": [
                {"source": "a", "target": "b", "type": "love", "confidence": 1.5},
            ],
        })


def test_name_length_limits():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({
            "characters": [{"name": ""}],
            "relationships": [],
        })


def test_self_loop_dropped():
    result = ExtractionResult.model_validate({
        "characters": [{"name": "贾宝玉"}],
        "relationships": [
            {"source": "贾宝玉", "target": "贾宝玉", "type": "love", "confidence": 0.9},
        ],
    })
    assert result.relationships == []
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_llm_client.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.schemas.llm'`）

- [ ] **Step 3: 写 schemas/llm.py**

```python
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class RelationshipType(str, Enum):
    love = "love"
    family = "family"
    friendship = "friendship"
    enmity = "enmity"
    alliance = "alliance"
    mentorship = "mentorship"
    other = "other"


class Character(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class Relationship(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    characters: list[Character]
    relationships: list[Relationship]

    @model_validator(mode="after")
    def drop_self_loops(self):
        """业务校验：source != target，self-loop 直接丢弃。"""
        self.relationships = [r for r in self.relationships if r.source != r.target]
        return self
```

- [ ] **Step 4: 运行确认通过**

```powershell
pytest tests/unit/test_llm_client.py -v
```

期望：5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/llm.py backend/tests/unit/test_llm_client.py
git commit -m "feat: LLM 输出契约（枚举/长度/置信度校验/self-loop 丢弃）"
```

---

### Task 4: pipeline/epub_reader.py（EPUB → 章节）

**Files:**
- Create: `backend/app/pipeline/epub_reader.py`
- Create: `backend/tests/epub_factory.py`（测试用 EPUB 构造 helper）
- Test: `backend/tests/unit/test_chunker.py`（第一部分：epub → 章节）

**Interfaces:**
- Consumes: 无
- Produces: `Chapter(chapter_id: int, chapter_title: str, text: str)`（dataclass）；`read_epub(epub_bytes: bytes) -> list[Chapter]`——按 spine 顺序编号，chapter_id 从 1 递增；空章节跳过

- [ ] **Step 1: 写 epub_factory.py（测试 helper）**

> 环境适配：本沙箱环境会锁定进程创建的临时目录（tmp_path/basetemp 不可用），故 `build_epub` 直接用 BytesIO 返回字节，不落盘；空章节不生成标题内容（保证剥离 HTML 后 text 为空，用于空章节跳过测试）。

```python
import io

from ebooklib import epub


def build_epub(chapters: list[str]) -> bytes:
    """构造一个章节为纯文本的测试 EPUB，直接返回文件字节（不落盘）。"""
    book = epub.EpubBook()
    book.set_identifier("test-001")
    book.set_title("测试小说")
    book.set_language("zh")
    spine = []
    for i, text in enumerate(chapters, start=1):
        c = epub.EpubHtml(title=f"第{i}章", file_name=f"chap_{i}.xhtml", lang="zh")
        # 空章节不生成标题/段落内容，确保剥离 HTML 后 text 为空（用于测试空章节跳过）
        c.content = f"<h1>第{i}章</h1><p>{text}</p>" if text else "<p></p>"
        book.add_item(c)
        spine.append(c)
    book.toc = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()
```

- [ ] **Step 2: 写失败测试（test_chunker.py 第一部分）**

```python
from app.pipeline.epub_reader import read_epub
from tests.epub_factory import build_epub


def test_read_epub_extracts_chapters_in_spine_order():
    epub_bytes = build_epub(["第一段内容。", "第二段内容。"])
    chapters = read_epub(epub_bytes)
    assert [c.chapter_title for c in chapters] == ["第1章", "第2章"]
    assert chapters[0].chapter_id == 1
    assert chapters[1].chapter_id == 2
    assert "第一段内容" in chapters[0].text
    assert "第二段内容" in chapters[1].text
    assert "<h1>" not in chapters[0].text  # HTML 标签已剥离


def test_read_epub_skips_empty_chapter():
    epub_bytes = build_epub(["", "有内容的章节。"])
    chapters = read_epub(epub_bytes)
    assert len(chapters) == 1
    assert chapters[0].chapter_id == 1
    assert "有内容的章节" in chapters[0].text
```

- [ ] **Step 3: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_chunker.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.pipeline.epub_reader'`）

- [ ] **Step 4: 写 epub_reader.py**

```python
import re
from dataclasses import dataclass
from io import BytesIO

from ebooklib import ITEM_DOCUMENT, epub

_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(nbsp|amp|lt|gt|quot);")


@dataclass
class Chapter:
    chapter_id: int
    chapter_title: str
    text: str


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub("", html)
    text = _ENTITY_RE.sub(lambda m: {
        "nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"',
    }[m.group(1)], text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def read_epub(epub_bytes: bytes) -> list[Chapter]:
    """按 spine 顺序解析 EPUB，返回章节纯文本列表。chapter_id 从 1 递增。"""
    book = epub.read_epub(BytesIO(epub_bytes))
    chapters: list[Chapter] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        text = _strip_html(item.get_content().decode("utf-8", errors="ignore"))
        if not text:
            continue
        title = (getattr(item, "title", "") or "").strip() or f"第{len(chapters) + 1}章"
        chapters.append(Chapter(chapter_id=len(chapters) + 1, chapter_title=title, text=text))
    return chapters
```

- [ ] **Step 5: 运行确认通过**

```powershell
pytest tests/unit/test_chunker.py -v
```

期望：2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/epub_reader.py backend/tests/epub_factory.py backend/tests/unit/test_chunker.py
git commit -m "feat: EPUB 按 spine 解析为章节（含 HTML 剥离）"
```

---

### Task 5: pipeline/chunker.py（章节 → 文本块）

**Files:**
- Create: `backend/app/pipeline/chunker.py`
- Test: `backend/tests/unit/test_chunker.py`（第二部分：切块）

**Interfaces:**
- Consumes: `Chapter`（Task 4）
- Produces: `Chunk(chunk_id: int, chapter_id: int, chapter_title: str, text: str, start_offset: int, end_offset: int)`（dataclass）；`chunk_chapters(chapters: list[Chapter], chunk_size: int, overlap: int) -> list[Chunk]`——整章 ≤ chunk_size 为一块；超长章按 chunk_size 切 + overlap 重叠；offset 为章节内字符偏移；chunk_id 全局递增

- [ ] **Step 1: 写失败测试（test_chunker.py 追加）**

```python
from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import Chapter


def test_chunk_short_chapter_is_single_chunk():
    chapter = Chapter(chapter_id=1, chapter_title="第一章", text="甲乙丙" * 10)
    chunks = chunk_chapters([chapter], chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == 1
    assert chunks[0].chapter_id == 1
    assert chunks[0].start_offset == 0
    assert chunks[0].end_offset == 30


def test_chunk_long_chapter_splits_with_overlap():
    chapter = Chapter(chapter_id=2, chapter_title="第二章", text="x" * 1000)
    chunks = chunk_chapters([chapter], chunk_size=300, overlap=50)
    assert len(chunks) == 4
    assert [c.start_offset for c in chunks] == [0, 250, 500, 750]
    assert chunks[0].end_offset == 300
    assert all(c.chapter_id == 2 for c in chunks)
    assert [c.chunk_id for c in chunks] == [1, 2, 3, 4]


def test_chunk_offsets_relative_to_chapter_text():
    chapter = Chapter(chapter_id=1, chapter_title="第一章", text="abcdefghij")
    chunks = chunk_chapters([chapter], chunk_size=4, overlap=1)
    assert chunks[0].start_offset == 0 and chunks[0].end_offset == 4
    assert chunks[1].start_offset == 3 and chunks[1].end_offset == 7
    assert chunks[2].start_offset == 6 and chunks[2].end_offset == 10


def test_chunk_ids_global_across_chapters():
    chapters = [
        Chapter(chapter_id=1, chapter_title="第一章", text="a" * 50),
        Chapter(chapter_id=2, chapter_title="第二章", text="b" * 500),
    ]
    chunks = chunk_chapters(chapters, chunk_size=300, overlap=0)
    assert [c.chunk_id for c in chunks] == [1, 2, 3]
    assert [c.chapter_id for c in chunks] == [1, 2, 2]
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_chunker.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.pipeline.chunker'`）

- [ ] **Step 3: 写 chunker.py**

```python
from dataclasses import dataclass

from app.pipeline.epub_reader import Chapter


@dataclass
class Chunk:
    chunk_id: int
    chapter_id: int
    chapter_title: str
    text: str
    start_offset: int
    end_offset: int


def chunk_chapters(chapters: list[Chapter], chunk_size: int, overlap: int) -> list[Chunk]:
    """章节 → 文本块。

    - 整章 ≤ chunk_size 为一块；
    - 超长章按 chunk_size 切，相邻块重叠 overlap 字符（同章内）；
    - offset 为相对该章节纯文本的字符偏移；
    - chunk_id 全局递增。
    """
    chunks: list[Chunk] = []
    chunk_id = 1
    for chapter in chapters:
        text = chapter.text
        if not text:
            continue
        if len(text) <= chunk_size:
            chunks.append(Chunk(chunk_id, chapter.chapter_id, chapter.chapter_title, text, 0, len(text)))
            chunk_id += 1
            continue
        step = max(1, chunk_size - overlap)
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(Chunk(chunk_id, chapter.chapter_id, chapter.chapter_title, text[start:end], start, end))
            chunk_id += 1
            if end == len(text):
                break
            start += step
    return chunks
```

- [ ] **Step 4: 运行确认通过**

```powershell
pytest tests/unit/test_chunker.py -v
```

期望：6 passed（2 epub 读取 + 4 切块）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/chunker.py backend/tests/unit/test_chunker.py
git commit -m "feat: 章节切块（章节内偏移/重叠/全局 chunk_id）"
```

---

### Task 6: pipeline/merger.py（聚合，锁死 weight 语义）

**Files:**
- Create: `backend/app/pipeline/merger.py`
- Test: `backend/tests/unit/test_merger.py`

**Interfaces:**
- Consumes: `Chunk`（Task 5）、`ExtractionResult` / `RelationshipType`（Task 3）
- Produces: `PersonAgg(name, mention_count, chapters)`、`RelAgg(source, target, type, chunk_ids, confidences, evidence)`（含 `weight`、`confidence` 属性）、`MergedGraph(persons: dict[str, PersonAgg], relationships: dict[tuple[str, str, RelationshipType], RelAgg])`；`merge_extractions(extractions: list[tuple[Chunk, ExtractionResult]]) -> MergedGraph`——按 `(source, target, type, chunk_id)` 去重，weight = distinct chunk 数，confidence = 算术平均，evidence 首现前 5 条，self-loop 防御性丢弃，输入按 chunk_id 排序保证确定性

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.merger import merge_extractions
from app.schemas.llm import ExtractionResult, Relationship, RelationshipType


def make_chunk(chunk_id, chapter_id=1, text="abc"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(relationships, characters=None):
    return ExtractionResult.model_validate({
        "characters": characters or [],
        "relationships": relationships,
    })


def test_same_chunk_duplicate_counts_once():
    """weight 语义锁死：同一 chunk 重复输出同一关系只计一次。"""
    chunk = make_chunk(1)
    result = extraction([
        {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.95},
        {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.90},
    ])
    graph = merge_extractions([(chunk, result)])
    rel = graph.relationships[("贾宝玉", "林黛玉", RelationshipType.love)]
    assert rel.weight == 1
    assert rel.chunk_ids == {1}
    assert rel.confidence == pytest.approx(0.95)  # 块内取首次置信度


def test_weight_counts_distinct_chunks():
    chunks = [make_chunk(1), make_chunk(7), make_chunk(12)]
    results = [
        extraction([{"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": c}])
        for c in (0.95, 0.90, 0.70)
    ]
    graph = merge_extractions(list(zip(chunks, results)))
    rel = graph.relationships[("贾宝玉", "林黛玉", RelationshipType.love)]
    assert rel.weight == 3
    assert rel.chunk_ids == {1, 7, 12}
    assert rel.confidence == pytest.approx(0.85)  # (0.95+0.90+0.70)/3


def test_evidence_first_five_by_discovery_order():
    chunks = [make_chunk(i) for i in range(1, 9)]
    results = [
        extraction([{"source": "A", "target": "B", "type": "other", "confidence": 0.8}])
        for _ in chunks
    ]
    graph = merge_extractions(list(zip(chunks, results)))
    rel = graph.relationships[("A", "B", RelationshipType.other)]
    assert rel.weight == 8
    assert [e["chunk_id"] for e in rel.evidence] == [1, 2, 3, 4, 5]
    assert len(rel.evidence) == 5


def test_mention_count_is_distinct_chunks():
    chunk1 = make_chunk(1)
    chunk2 = make_chunk(2, chapter_id=2)
    r1 = extraction(
        [{"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.9}],
        characters=[{"name": "贾宝玉"}],
    )
    r2 = extraction([], characters=[{"name": "贾宝玉"}, {"name": "林黛玉"}])
    graph = merge_extractions([(chunk1, r1), (chunk2, r2)])
    assert graph.persons["贾宝玉"].mention_count == 2
    assert graph.persons["贾宝玉"].chapters == {1, 2}
    assert graph.persons["林黛玉"].mention_count == 1


def test_merger_defensively_skips_self_loop():
    chunk = make_chunk(1)
    result = ExtractionResult.model_construct(characters=[], relationships=[
        Relationship(source="A", target="A", type=RelationshipType.other, confidence=0.5),
    ])
    graph = merge_extractions([(chunk, result)])
    assert graph.relationships == {}


def test_merge_is_deterministic_regardless_of_input_order():
    chunks = [make_chunk(2), make_chunk(1)]
    results = [
        extraction([{"source": "A", "target": "B", "type": "other", "confidence": 0.8}])
        for _ in chunks
    ]
    graph = merge_extractions(list(zip(chunks, results)))
    rel = graph.relationships[("A", "B", RelationshipType.other)]
    assert [e["chunk_id"] for e in rel.evidence] == [1, 2]  # 按 chunk_id 排序后首现顺序
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_merger.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.pipeline.merger'`）

- [ ] **Step 3: 写 merger.py**

```python
from dataclasses import dataclass, field

from app.pipeline.chunker import Chunk
from app.schemas.llm import ExtractionResult, RelationshipType

EVIDENCE_CAP = 5


@dataclass
class PersonAgg:
    name: str
    mention_count: int = 0
    chapters: set[int] = field(default_factory=set)


@dataclass
class RelAgg:
    source: str
    target: str
    type: RelationshipType
    chunk_ids: set[int] = field(default_factory=set)
    confidences: list[float] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return len(self.chunk_ids)

    @property
    def confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0


@dataclass
class MergedGraph:
    persons: dict[str, PersonAgg] = field(default_factory=dict)
    relationships: dict[tuple[str, str, RelationshipType], RelAgg] = field(default_factory=dict)


def merge_extractions(extractions: list[tuple[Chunk, ExtractionResult]]) -> MergedGraph:
    """按 chunk 聚合。

    - 唯一输入单位 chunk_id：同 (source, target, type) 在一个 chunk 内只计一次；
    - weight = 确认该关系的不同 chunk 数（distinct chunk_id）；
    - confidence = 各确认 chunk confidence 的算术平均（块内重复取首次值）；
    - evidence 按首次发现顺序保留前 EVIDENCE_CAP 条，之后不再追加；
    - 输入先按 chunk_id 排序，保证首次发现顺序确定（多次运行结果稳定）。
    """
    graph = MergedGraph()
    for chunk, result in sorted(extractions, key=lambda e: e[0].chunk_id):
        seen_names: set[str] = set()
        for c in result.characters:
            seen_names.add(c.name)
        for r in result.relationships:
            if r.source == r.target:
                continue  # 防御：self-loop 直接丢弃
            # 注：mention_count 只统计 characters 字段（关系端点不计入），
            # 与 test_mention_count_is_distinct_chunks 断言一致
            rel = graph.relationships.setdefault(
                (r.source, r.target, r.type),
                RelAgg(source=r.source, target=r.target, type=r.type),
            )
            if chunk.chunk_id not in rel.chunk_ids:
                rel.chunk_ids.add(chunk.chunk_id)
                rel.confidences.append(r.confidence)
                if len(rel.evidence) < EVIDENCE_CAP:
                    rel.evidence.append({
                        "chunk_id": chunk.chunk_id,
                        "chapter_id": chunk.chapter_id,
                        "text": chunk.text,
                    })
        for name in seen_names:
            person = graph.persons.setdefault(name, PersonAgg(name=name))
            person.mention_count += 1
            person.chapters.add(chunk.chapter_id)
    return graph
```

- [ ] **Step 4: 运行确认通过**

```powershell
pytest tests/unit/test_merger.py -v
```

期望：6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/merger.py backend/tests/unit/test_merger.py
git commit -m "feat: merger 聚合（weight=distinct chunk/置信度平均/evidence 首现前5）"
```

---

### Task 7: pipeline/llm_client.py + extractor.py（LLM 调用与并发抽取）

**Files:**
- Create: `backend/app/pipeline/llm_client.py`
- Create: `backend/app/pipeline/extractor.py`
- Test: `backend/tests/unit/test_llm_client.py`（第二部分：client 重试/失败分类/并发）

**Interfaces:**
- Consumes: `Chunk`（Task 5）、`ExtractionResult`（Task 3）
- Produces:
  - `LLMClient(base_url, api_key, model, http_client=None)`，方法 `extract_chunk(text: str) -> ExtractionResult`；异常：`LLMError`（基类）、`LLMRetryableError`（429/5xx，消息如 `"http_429"`）、`LLMValidationError`（消息 `"invalid_response_shape"` / `"validation_error"`）
  - `FailedBlock(chunk_id: int, chapter_id: int, error: str)`（dataclass）
  - `ExtractionBundle(results: list[tuple[Chunk, ExtractionResult]], failed: list[FailedBlock])`
  - `extract_all(client, chunks, concurrency=4, on_chunk_done=None) -> ExtractionBundle`——ThreadPoolExecutor 并发；429/5xx 重试 1 次（退避 0.5s×(attempt+1)）；validation error 不重试；意外异常按可重试处理 1 次；`on_chunk_done()` 每处理完一个 chunk 调用一次（进度回调）；结果按 chunk_id 排序

- [ ] **Step 1: 写失败测试（test_llm_client.py 追加）**

```python
import httpx
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.extractor import FailedBlock, extract_all
from app.pipeline.llm_client import LLMClient
from app.schemas.llm import ExtractionResult

VALID_JSON = {
    "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}],
    "relationships": [
        {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.9},
    ],
}


def make_chunk(chunk_id):
    return Chunk(chunk_id=chunk_id, chapter_id=1, chapter_title="第1章",
                 text="文本", start_offset=0, end_offset=2)


class FakeHttpClient:
    """模拟 httpx.Client：按队列依次返回预置响应。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, url, json=None):
        self.calls += 1
        return self.responses.pop(0)


def fake_response(status_code, payload=None):
    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    return _Resp(status_code, payload)


def make_client(responses):
    return LLMClient(base_url="http://fake", api_key="k", model="m",
                     http_client=FakeHttpClient(responses))


def test_extract_chunk_parses_valid_json():
    client = make_client([fake_response(200, {
        "choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}],
    })])
    result = client.extract_chunk("任意文本")
    assert isinstance(result, ExtractionResult)


def test_extract_chunk_malformed_json_is_validation_error():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": "不是JSON"}}]})])
    with pytest.raises(Exception) as exc:
        client.extract_chunk("任意文本")
    assert "validation_error" in str(exc.value)


def test_retryable_error_retried_once_then_succeeds():
    client = make_client([
        fake_response(429),
        fake_response(200, {"choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}]}),
    ])
    chunk = make_chunk(1)
    out = extract_one(client, chunk)
    assert isinstance(out, tuple)
    assert client._client.calls == 2


def test_retryable_error_fails_after_retries_exhausted():
    client = make_client([fake_response(500), fake_response(500)])
    chunk = make_chunk(1)
    out = extract_one(client, chunk)
    assert isinstance(out, FailedBlock)
    assert out.error == "http_500"


def test_validation_error_not_retried():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": '{"bad": 1}'}}]})])
    chunk = make_chunk(1)
    out = extract_one(client, chunk)
    assert isinstance(out, FailedBlock)
    assert out.error == "validation_error"
    assert client._client.calls == 1


def test_extract_all_sorts_and_counts_and_callback():
    chunks = [make_chunk(2), make_chunk(1)]
    client = make_client([
        fake_response(200, {"choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}]}),
        fake_response(200, {"choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}]}),
    ])
    calls = []
    bundle = extract_all(client, chunks, concurrency=2, on_chunk_done=lambda: calls.append(1))
    assert [c.chunk_id for c, _ in bundle.results] == [1, 2]
    assert bundle.failed == []
    assert len(calls) == 2
```

> 注意：`extract_one` 是 extractor 内部函数，测试中从 `app.pipeline.extractor import extract_one` 导入（与 `extract_all` 同文件）。

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_llm_client.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.pipeline.llm_client'`）

- [ ] **Step 3: 写 llm_client.py**

```python
import httpx
from pydantic import ValidationError

from app.schemas.llm import ExtractionResult

EXTRACTION_SYSTEM_PROMPT = """你是小说人物关系抽取器。给定一段小说文本，抽取其中明确出现的人物，以及人物之间明确的关系。
严格要求：
1. 只抽取文本中明确出现的人物与关系，不要臆测。
2. characters: 文本中出现的人物姓名列表（同一人物按文本中的写法输出，不要合并别名）。
3. relationships: 人物之间的关系。source 是当前文本片段中作为关系主体的人物，target 是与其发生关系的人物。
4. type 只能使用以下 7 个枚举值之一：love（爱情）、family（血缘/家族）、friendship（友谊）、enmity（敌对/仇怨）、alliance（结盟/合作）、mentorship（师徒/师生）、other（其他无法归类的明确关系）。禁止自创类型，如 romantic、lover、亲密、爱情、love_relation 等一律归入 love。
5. confidence: 0 到 1 之间的浮点数，表示你对这条关系判断的把握程度。
6. 只输出 JSON 对象，不要输出任何其他文字。格式：
{"characters": [{"name": "..."}], "relationships": [{"source": "...", "target": "...", "type": "love", "confidence": 0.9}]}"""

EXTRACTION_USER_PROMPT = "请抽取以下文本中的人物与关系：\n\n{text}"


class LLMError(Exception):
    """LLM 抽取失败基类。"""


class LLMRetryableError(LLMError):
    """可重试错误：429 / 5xx。"""


class LLMValidationError(LLMError):
    """不可重试错误：JSON 解析失败或 Pydantic 校验失败。"""


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, http_client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.Client(timeout=60)

    def extract_chunk(self, text: str) -> ExtractionResult:
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": EXTRACTION_USER_PROMPT.format(text=text)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMRetryableError(f"http_{response.status_code}")
        if response.status_code >= 400:
            raise LLMError(f"http_{response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMValidationError("invalid_response_shape") from exc
        try:
            return ExtractionResult.model_validate_json(content)
        except ValidationError as exc:
            raise LLMValidationError("validation_error") from exc
```

- [ ] **Step 4: 写 extractor.py**

```python
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.pipeline.chunker import Chunk
from app.pipeline.llm_client import LLMClient, LLMRetryableError, LLMValidationError
from app.schemas.llm import ExtractionResult


@dataclass
class FailedBlock:
    chunk_id: int
    chapter_id: int
    error: str


@dataclass
class ExtractionBundle:
    results: list[tuple[Chunk, ExtractionResult]]
    failed: list[FailedBlock]


def extract_one(client: LLMClient, chunk: Chunk, retries: int = 1):
    """单块抽取。429/5xx 与意外异常重试 retries 次；validation error 不重试。"""
    for attempt in range(retries + 1):
        try:
            return chunk, client.extract_chunk(chunk.text)
        except LLMRetryableError as exc:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return FailedBlock(chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id, error=str(exc))
        except LLMValidationError as exc:
            return FailedBlock(chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id, error=str(exc))
        except Exception as exc:  # 网络中断等意外错误，按可重试处理
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return FailedBlock(
                chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id,
                error=f"unexpected:{type(exc).__name__}",
            )


def extract_all(client: LLMClient, chunks: list[Chunk], concurrency: int = 4,
                on_chunk_done=None) -> ExtractionBundle:
    """并发抽取全部 chunk。concurrency 必须来自配置，禁止写死。"""
    results: list[tuple[Chunk, ExtractionResult]] = []
    failed: list[FailedBlock] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(extract_one, client, c) for c in chunks]
        for fut in as_completed(futures):
            out = fut.result()
            if isinstance(out, FailedBlock):
                failed.append(out)
            else:
                results.append(out)
            if on_chunk_done is not None:
                on_chunk_done()
    results.sort(key=lambda e: e[0].chunk_id)
    failed.sort(key=lambda f: f.chunk_id)
    return ExtractionBundle(results=results, failed=failed)
```

- [ ] **Step 5: 运行确认通过**

```powershell
pytest tests/unit/test_llm_client.py -v
```

期望：10 passed（5 契约 + 5 抽取；含重试 0.5s×2 的耗时用例）

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/llm_client.py backend/app/pipeline/extractor.py backend/tests/unit/test_llm_client.py
git commit -m "feat: LLM 客户端与并发抽取（失败分类/重试/进度回调）"
```

---

### Task 8: models/job.py（Job 状态模型 + 进程内存储）

**Files:**
- Create: `backend/app/models/job.py`
- Test: `backend/tests/unit/test_job_store.py`

**Interfaces:**
- Consumes: 无
- Produces: `JobStatus`（Enum：pending/running/completed/completed_with_errors/failed）、`FailedBlock(chunk_id, chapter_id, error)`（BaseModel）、`JobState(job_id, novel_id, status, done_chunks, total_chunks, failed_blocks, stats, error)`（BaseModel）、`JobStore`（线程安全）：`create(job_id, novel_id) -> JobState`、`get(job_id) -> JobState | None`、`update(job_id, **fields) -> JobState | None`、`increment_done(job_id) -> None`

- [ ] **Step 1: 写失败测试**

```python
import threading

from app.models.job import FailedBlock, JobStatus, JobStore


def test_job_lifecycle():
    store = JobStore()
    job = store.create("job-1", "novel-1")
    assert job.status == JobStatus.pending
    store.update("job-1", status=JobStatus.running, total_chunks=10)
    store.update("job-1", status=JobStatus.completed_with_errors,
                 done_chunks=9,
                 failed_blocks=[FailedBlock(chunk_id=3, chapter_id=1, error="validation_error")],
                 stats={"persons": 10, "relationships": 5})
    state = store.get("job-1")
    assert state.status == JobStatus.completed_with_errors
    assert state.stats["persons"] == 10
    assert state.failed_blocks[0].chunk_id == 3


def test_unknown_job_returns_none():
    store = JobStore()
    assert store.get("nope") is None


def test_increment_done_is_thread_safe():
    store = JobStore()
    store.create("job-1", "novel-1")
    errors = []

    def bump():
        try:
            for _ in range(100):
                store.increment_done("job-1")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert store.get("job-1").done_chunks == 400
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest tests/unit/test_job_store.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.models.job'`）

- [ ] **Step 3: 写 models/job.py**

```python
from enum import Enum
from threading import Lock

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"


class FailedBlock(BaseModel):
    chunk_id: int
    chapter_id: int
    error: str


class JobState(BaseModel):
    job_id: str
    novel_id: str
    status: JobStatus = JobStatus.pending
    done_chunks: int = 0
    total_chunks: int = 0
    failed_blocks: list[FailedBlock] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    error: str | None = None


class JobStore:
    """进程内任务存储（V0.1 设计决策：单进程足够，不引入 Redis）。

    注意：进程重启后任务丢失，后续版本替换为持久化任务存储。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()

    def create(self, job_id: str, novel_id: str) -> JobState:
        with self._lock:
            job = JobState(job_id=job_id, novel_id=novel_id)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> JobState | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                setattr(job, key, value)
            return job

    def increment_done(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.done_chunks += 1
```

- [ ] **Step 4: 运行确认通过**

```powershell
pytest tests/unit/test_job_store.py -v
```

期望：3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/job.py backend/tests/unit/test_job_store.py
git commit -m "feat: Job 状态模型与线程安全进程内存储"
```

---

### Task 9: db/neo4j.py（写库与查询）

**Files:**
- Create: `backend/app/db/neo4j.py`
- Test: `backend/tests/integration/test_api_neo4j.py`（第一部分：db 层，`@pytest.mark.integration`）

**Interfaces:**
- Consumes: `MergedGraph` / `PersonAgg` / `RelAgg`（Task 6）、`RelationshipType`（Task 3）、`get_settings()`（Task 2）
- Produces: `Neo4jDB(uri, user, password)` 方法：`close()`、`ping()`、`ensure_constraints()`（幂等，两个唯一约束）、`upsert_novel(novel_id, title, chapters: list[dict])`、`upsert_graph(novel_id, merged)`、`get_novel(novel_id) -> dict | None`、`search_characters(novel_id, q, limit=10) -> list[dict]`、`get_character(novel_id, character_id) -> dict | None`、`get_subgraph(novel_id, character_id) -> dict | None`（节点带 `is_center`，边带 `source_id/target_id/type/weight/confidence/evidence`，evidence 补 `chapter_title`）、`count_stats(novel_id) -> dict`、`delete_novel(novel_id)`（测试清理用）

- [ ] **Step 1: 写失败测试（integration 第一部分）**

```python
import uuid

import pytest

from app.config import get_settings
from app.db.neo4j import Neo4jDB
from app.pipeline.merger import MergedGraph, PersonAgg, RelAgg
from app.schemas.llm import RelationshipType

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db():
    settings = get_settings()
    database = Neo4jDB(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        database.ping()
    except Exception:
        pytest.skip("Neo4j 不可达：请先 `docker compose up -d neo4j` 并配置 .env")
    database.ensure_constraints()
    yield database
    database.close()


def build_merged():
    return MergedGraph(
        persons={
            "贾宝玉": PersonAgg(name="贾宝玉", mention_count=3, chapters={1, 2}),
            "林黛玉": PersonAgg(name="林黛玉", mention_count=2, chapters={1}),
            "王熙凤": PersonAgg(name="王熙凤", mention_count=1, chapters={2}),
        },
        relationships={
            ("贾宝玉", "林黛玉", RelationshipType.love): RelAgg(
                source="贾宝玉", target="林黛玉", type=RelationshipType.love,
                chunk_ids={1, 7, 12}, confidences=[0.95, 0.9, 0.7],
                evidence=[{"chunk_id": 1, "chapter_id": 1, "text": "贾宝玉和林黛玉交谈。"}],
            ),
            ("王熙凤", "贾宝玉", RelationshipType.enmity): RelAgg(
                source="王熙凤", target="贾宝玉", type=RelationshipType.enmity,
                chunk_ids={2}, confidences=[0.8], evidence=[],
            ),
        },
    )


@pytest.fixture()
def novel_id(db):
    nid = f"test-{uuid.uuid4()}"
    yield nid
    db.delete_novel(nid)


def test_ensure_constraints_idempotent(db):
    db.ensure_constraints()
    db.ensure_constraints()  # 幂等，不抛错


def test_upsert_and_subgraph(db, novel_id):
    db.upsert_novel(novel_id, "测试小说", [{"id": 1, "title": "第1章"}, {"id": 2, "title": "第2章"}])
    db.upsert_graph(novel_id, build_merged())

    novel = db.get_novel(novel_id)
    assert novel["title"] == "测试小说"
    assert [c["id"] for c in novel["chapters"]] == [1, 2]

    cands = db.search_characters(novel_id, "贾")
    assert any(c["name"] == "贾宝玉" for c in cands)

    center = db.get_character(novel_id, cands[0]["id"])
    assert center["name"] == "贾宝玉"

    graph = db.get_subgraph(novel_id, center["id"])
    assert {n["name"] for n in graph["nodes"]} == {"贾宝玉", "林黛玉", "王熙凤"}
    center_node = next(n for n in graph["nodes"] if n["is_center"])
    assert center_node["name"] == "贾宝玉"

    love_edge = next(e for e in graph["edges"] if e["type"] == "love")
    assert love_edge["weight"] == 3
    assert love_edge["confidence"] == pytest.approx(0.85)
    assert love_edge["evidence"][0]["chapter_title"] == "第1章"
    assert love_edge["source_id"] == center["id"]

    stats = db.count_stats(novel_id)
    assert stats == {"persons": 3, "relationships": 2}


def test_subgraph_unknown_character_returns_none(db, novel_id):
    db.upsert_novel(novel_id, "测试小说", [])
    assert db.get_subgraph(novel_id, "no-such-id") is None
```

> 说明：`cands[0]["id"]` 为「贾宝玉」或「贾雨村」等含「贾」的人物——`build_merged` 只有「贾宝玉」含「贾」，故断言安全。

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
# 前置：cp ../.env.example .env 并确认 Neo4j 已启动（docker compose up -d neo4j）
pytest -m integration tests/integration/test_api_neo4j.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.db.neo4j'`）

- [ ] **Step 3: 写 db/neo4j.py**

```python
from uuid import uuid4

from neo4j import GraphDatabase


class Neo4jDB:
    """Neo4j 封装。所有查询都按 novel_id 隔离；关系查询用 novel_id + character_id 双层隔离。"""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def ping(self) -> None:
        with self._driver.session() as session:
            session.run("RETURN 1").consume()

    def ensure_constraints(self) -> None:
        """幂等创建唯一约束（Neo4j 5.x 语法）。"""
        statements = [
            "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT person_novel_name IF NOT EXISTS FOR (p:Person) REQUIRE (p.novel_id, p.name) IS UNIQUE",
        ]
        with self._driver.session() as session:
            for stmt in statements:
                session.run(stmt).consume()

    def upsert_novel(self, novel_id: str, title: str, chapters: list[dict]) -> None:
        with self._driver.session() as session:
            session.run(
                "MERGE (n:Novel {id: $novel_id}) SET n.title = $title, n.chapters = $chapters",
                novel_id=novel_id, title=title, chapters=chapters,
            ).consume()

    def upsert_graph(self, novel_id: str, merged) -> None:
        """merged: pipeline.merger.MergedGraph"""
        with self._driver.session() as session:
            for name, person in merged.persons.items():
                session.run(
                    """MERGE (p:Person {novel_id: $novel_id, name: $name})
                       ON CREATE SET p.id = $person_id
                       SET p.mention_count = $mention_count, p.chapters = $chapters""",
                    novel_id=novel_id, name=name, person_id=str(uuid4()),
                    mention_count=person.mention_count, chapters=sorted(person.chapters),
                ).consume()
            for (source, target, rtype), rel in merged.relationships.items():
                session.run(
                    """MATCH (a:Person {novel_id: $novel_id, name: $source})
                       MATCH (b:Person {novel_id: $novel_id, name: $target})
                       MERGE (a)-[r:RELATES_TO {novel_id: $novel_id, source: $source, target: $target, type: $type}]->(b)
                       SET r.chunk_ids = $chunk_ids, r.weight = $weight,
                           r.confidence = $confidence, r.evidence = $evidence""",
                    novel_id=novel_id, source=source, target=target, type=rtype.value,
                    chunk_ids=sorted(rel.chunk_ids), weight=rel.weight,
                    confidence=rel.confidence, evidence=rel.evidence,
                ).consume()

    def get_novel(self, novel_id: str) -> dict | None:
        with self._driver.session() as session:
            record = session.run(
                "MATCH (n:Novel {id: $novel_id}) RETURN n.title AS title, n.chapters AS chapters",
                novel_id=novel_id,
            ).single()
            if record is None:
                return None
            return {"id": novel_id, "title": record["title"], "chapters": record["chapters"] or []}

    def search_characters(self, novel_id: str, q: str, limit: int = 10) -> list[dict]:
        with self._driver.session() as session:
            records = session.run(
                """MATCH (p:Person)
                   WHERE p.novel_id = $novel_id AND p.name CONTAINS $q
                   RETURN p.id AS id, p.name AS name, p.mention_count AS mention_count
                   ORDER BY p.mention_count DESC
                   LIMIT $limit""",
                novel_id=novel_id, q=q, limit=limit,
            )
            return [dict(r) for r in records]

    def get_character(self, novel_id: str, character_id: str) -> dict | None:
        with self._driver.session() as session:
            record = session.run(
                """MATCH (p:Person {id: $character_id})
                   WHERE p.novel_id = $novel_id
                   RETURN p.id AS id, p.name AS name, p.mention_count AS mention_count""",
                novel_id=novel_id, character_id=character_id,
            ).single()
            return dict(record) if record else None

    def get_subgraph(self, novel_id: str, character_id: str) -> dict | None:
        """1 跳子图（无向遍历，边保留存储方向）。novel_id + character_id 双层隔离。"""
        center = self.get_character(novel_id, character_id)
        if center is None:
            return None
        with self._driver.session() as session:
            records = session.run(
                """MATCH (c:Person {id: $character_id})
                   WHERE c.novel_id = $novel_id
                   MATCH (c)-[r:RELATES_TO]-(n:Person)
                   WHERE n.novel_id = $novel_id
                   RETURN n.id AS node_id, n.name AS node_name, n.mention_count AS node_mention_count,
                          r.type AS r_type, r.weight AS r_weight, r.confidence AS r_confidence,
                          r.evidence AS r_evidence,
                          startNode(r).id AS r_from_id, endNode(r).id AS r_to_id""",
                novel_id=novel_id, character_id=character_id,
            )
        novel = self.get_novel(novel_id)
        chapter_titles = {c["id"]: c["title"] for c in (novel["chapters"] if novel else [])}
        nodes = {character_id: {**center, "is_center": True}}
        edges: list[dict] = []
        for rec in records:
            nid = rec["node_id"]
            if nid not in nodes:
                nodes[nid] = {
                    "id": nid,
                    "name": rec["node_name"],
                    "mention_count": rec["node_mention_count"],
                    "is_center": False,
                }
            evidence = []
            for item in rec["r_evidence"] or []:
                evidence.append({
                    "chunk_id": item["chunk_id"],
                    "chapter_id": item["chapter_id"],
                    "chapter_title": chapter_titles.get(item["chapter_id"], ""),
                    "text": item["text"],
                })
            edges.append({
                "source_id": rec["r_from_id"],
                "target_id": rec["r_to_id"],
                "type": rec["r_type"],
                "weight": rec["r_weight"],
                "confidence": rec["r_confidence"],
                "evidence": evidence,
            })
        return {"nodes": list(nodes.values()), "edges": edges}

    def count_stats(self, novel_id: str) -> dict:
        with self._driver.session() as session:
            persons = session.run(
                "MATCH (p:Person) WHERE p.novel_id = $novel_id RETURN count(p) AS c",
                novel_id=novel_id,
            ).single()["c"]
            relationships = session.run(
                "MATCH (:Person)-[r:RELATES_TO]->(:Person) WHERE r.novel_id = $novel_id RETURN count(r) AS c",
                novel_id=novel_id,
            ).single()["c"]
            return {"persons": persons, "relationships": relationships}

    def delete_novel(self, novel_id: str) -> None:
        """测试清理用：删除某小说全部节点与关系。"""
        with self._driver.session() as session:
            session.run("MATCH (p:Person) WHERE p.novel_id = $novel_id DETACH DELETE p", novel_id=novel_id).consume()
            session.run("MATCH (n:Novel) WHERE n.id = $novel_id DELETE n", novel_id=novel_id).consume()
```

- [ ] **Step 4: 运行确认通过**

```powershell
pytest -m integration tests/integration/test_api_neo4j.py -v
```

期望：3 passed（前置：.env 已配置、Neo4j 已启动）

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/neo4j.py backend/tests/integration/test_api_neo4j.py
git commit -m "feat: Neo4j 读写层（约束/upsert/1跳子图/novel_id 隔离）"
```

---

### Task 10: API 层 + main.py + 端到端集成测试

**Files:**
- Create: `backend/app/schemas/api.py`
- Create: `backend/app/api/novels.py`（含 `_run_ingest` 编排）
- Create: `backend/app/api/jobs.py`
- Create: `backend/app/api/characters.py`
- Create: `backend/app/api/health.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/integration/test_api_neo4j.py`（第二部分：端到端 upload → job → graph，FakeLLMClient 替换真实 LLM）

**Interfaces:**
- Consumes: 全部前置模块（Settings、Chunk/Chapter、LLMClient、extract_all、merge_extractions、Neo4jDB、JobStore/JobState）
- Produces: FastAPI 应用 `app`（`app.main:app`）；`app.state.settings / job_store / db / llm_client`；端点：`POST /api/novels`（multipart .epub → `{novel_id, job_id}`，非 epub 400、空文件 400、>50MB 413、Neo4j 不可达 503）、`GET /api/jobs/{job_id}`（404 未知 job）、`GET /api/novels/{novel_id}`、`GET /api/novels/{novel_id}/characters?q=`、`GET /api/characters/{character_id}/graph`、`GET /api/health`（Neo4j 不可达 503）

- [ ] **Step 1: 写失败测试（integration 第二部分，追加到 test_api_neo4j.py）**

```python
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.llm import ExtractionResult


class FakeLLMClient:
    """固定返回两组关系（两个 chunk 都确认 love/enmity），验证 weight=2 贯穿全链路。"""

    def extract_chunk(self, text: str) -> ExtractionResult:
        return ExtractionResult.model_validate({
            "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}, {"name": "王熙凤"}],
            "relationships": [
                {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.9},
                {"source": "王熙凤", "target": "贾宝玉", "type": "enmity", "confidence": 0.8},
            ],
        })


@pytest.fixture(scope="module")
def client(db):
    app = create_app()
    with TestClient(app) as client:
        app.state.llm_client = FakeLLMClient()  # 替换真实 LLM，其余（db/job_store）走 lifespan
        yield client


@pytest.fixture()
def uploaded(client):
    from tests.epub_factory import build_epub

    epub_bytes = build_epub(["贾宝玉和林黛玉在大观园交谈。", "王熙凤对贾宝玉发怒。"])
    resp = client.post("/api/novels", files={"file": ("flow.epub", epub_bytes, "application/epub+zip")})
    assert resp.status_code == 200
    data = resp.json()
    yield data  # {"novel_id", "job_id"}
    client.app.state.db.delete_novel(data["novel_id"])


def _wait_job(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job 超时未结束")


def test_upload_to_graph_full_flow(client, uploaded):
    novel_id, job_id = uploaded["novel_id"], uploaded["job_id"]

    job = _wait_job(client, job_id)
    assert job["status"] == "completed"
    assert job["stats"]["persons"] == 3
    assert job["stats"]["relationships"] == 2

    novel = client.get(f"/api/novels/{novel_id}").json()
    assert [c["id"] for c in novel["chapters"]] == [1, 2]

    cands = client.get(f"/api/novels/{novel_id}/characters", params={"q": "贾"}).json()
    jia = next(c for c in cands if c["name"] == "贾宝玉")

    graph = client.get(f"/api/characters/{jia['id']}/graph").json()
    assert {n["name"] for n in graph["nodes"]} == {"贾宝玉", "林黛玉", "王熙凤"}
    love_edge = next(e for e in graph["edges"] if e["type"] == "love")
    assert love_edge["weight"] == 2            # 两个 chunk 都确认 → weight 语义贯穿全链路
    assert love_edge["confidence"] == pytest.approx(0.9)
    assert love_edge["evidence"][0]["chapter_title"] == "第1章"


def test_upload_rejects_non_epub(client):
    resp = client.post("/api/novels", files={"file": ("a.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_unknown_character_404(client, uploaded):
    resp = client.get("/api/characters/no-such-id/graph")
    assert resp.status_code == 404


def test_unknown_job_404(client):
    assert client.get("/api/jobs/no-such-job").status_code == 404


def test_health_ok(client):
    assert client.get("/api/health").json()["status"] == "ok"
```

> 说明：integration 第二部分在同一文件内继续追加；`db` fixture（第一部分）提供 Neo4j 连通性前置。`create_app()` 在 main.py 实现后可用。

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\backend
pytest -m integration tests/integration/test_api_neo4j.py -v
```

期望：FAIL（`ModuleNotFoundError: No module named 'app.main'`）

- [ ] **Step 3: 写 schemas/api.py**

```python
from pydantic import BaseModel

from app.models.job import FailedBlock, JobState, JobStatus


class NovelCreateResponse(BaseModel):
    novel_id: str
    job_id: str


class JobProgress(BaseModel):
    done_chunks: int
    total_chunks: int


class JobResponse(BaseModel):
    job_id: str
    novel_id: str
    status: JobStatus
    progress: JobProgress
    failed_blocks: list[FailedBlock]
    stats: dict
    error: str | None = None

    @classmethod
    def from_state(cls, state: JobState) -> "JobResponse":
        return cls(
            job_id=state.job_id,
            novel_id=state.novel_id,
            status=state.status,
            progress=JobProgress(done_chunks=state.done_chunks, total_chunks=state.total_chunks),
            failed_blocks=state.failed_blocks,
            stats=state.stats,
            error=state.error,
        )


class NovelResponse(BaseModel):
    id: str
    title: str
    chapters: list[dict]
    stats: dict


class CharacterCandidate(BaseModel):
    id: str
    name: str
    mention_count: int


class EvidenceItem(BaseModel):
    chunk_id: int
    chapter_id: int
    chapter_title: str
    text: str


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    type: str
    weight: int
    confidence: float
    evidence: list[EvidenceItem]


class GraphNode(BaseModel):
    id: str
    name: str
    mention_count: int
    is_center: bool


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
```

- [ ] **Step 4: 写 api/novels.py（含 ingest 编排）**

```python
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile

from app.config import Settings
from app.db.neo4j import Neo4jDB
from app.models.job import JobStore, JobStatus
from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import read_epub
from app.pipeline.extractor import extract_all
from app.pipeline.llm_client import LLMClient
from app.pipeline.merger import merge_extractions
from app.schemas.api import NovelCreateResponse

router = APIRouter(prefix="/api/novels", tags=["novels"])

MAX_EPUB_BYTES = 50 * 1024 * 1024  # 50MB


def _run_ingest(novel_id: str, job_id: str, title: str, epub_bytes: bytes,
                settings: Settings, db: Neo4jDB, job_store: JobStore, llm_client: LLMClient) -> None:
    """后台 ingest 任务：epub → 章节 → 切块 → 并发抽取 → 聚合 → 写库 → 更新 job。"""
    job_store.update(job_id, status=JobStatus.running)
    try:
        chapters = read_epub(epub_bytes)
        if not chapters:
            raise ValueError("epub 中没有可解析的章节内容")
        chunks = chunk_chapters(chapters, settings.chunk_size, settings.chunk_overlap)
        job_store.update(job_id, total_chunks=len(chunks))
        bundle = extract_all(
            llm_client, chunks,
            concurrency=settings.llm_concurrency,
            on_chunk_done=lambda: job_store.increment_done(job_id),
        )
        merged = merge_extractions(bundle.results)
        db.upsert_novel(novel_id, title, [{"id": c.chapter_id, "title": c.chapter_title} for c in chapters])
        db.upsert_graph(novel_id, merged)
        stats = db.count_stats(novel_id)
        if bundle.failed:
            job_store.update(
                job_id, status=JobStatus.completed_with_errors,
                failed_blocks=[{"chunk_id": f.chunk_id, "chapter_id": f.chapter_id, "error": f.error}
                               for f in bundle.failed],
                stats=stats,
            )
        else:
            job_store.update(job_id, status=JobStatus.completed, stats=stats)
    except Exception as exc:
        job_store.update(job_id, status=JobStatus.failed, error=str(exc))


@router.post("", response_model=NovelCreateResponse)
async def create_novel(request: Request, background_tasks: BackgroundTasks,
                       file: UploadFile = File(...)) -> NovelCreateResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="仅支持 .epub 文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_EPUB_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")

    db: Neo4jDB = request.app.state.db
    try:
        db.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Neo4j 不可达")

    novel_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    title = Path(filename).stem
    job_store: JobStore = request.app.state.job_store
    job_store.create(job_id, novel_id)
    background_tasks.add_task(
        _run_ingest, novel_id, job_id, title, data,
        request.app.state.settings, db, job_store, request.app.state.llm_client,
    )
    return NovelCreateResponse(novel_id=novel_id, job_id=job_id)
```

- [ ] **Step 5: 写 api/jobs.py / api/characters.py / api/health.py**

```python
# api/jobs.py
from fastapi import APIRouter, HTTPException, Request

from app.schemas.api import JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request) -> JobResponse:
    state = request.app.state.job_store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="job 不存在")
    return JobResponse.from_state(state)
```

```python
# api/characters.py
from fastapi import APIRouter, HTTPException, Request

from app.schemas.api import CharacterCandidate, GraphResponse

router = APIRouter(prefix="/api", tags=["characters"])


@router.get("/novels/{novel_id}/characters", response_model=list[CharacterCandidate])
def search_characters(novel_id: str, q: str = "", request: Request) -> list[CharacterCandidate]:
    db = request.app.state.db
    if db.get_novel(novel_id) is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return db.search_characters(novel_id, q, limit=10)


@router.get("/characters/{character_id}/graph", response_model=GraphResponse)
def get_character_graph(character_id: str, request: Request) -> GraphResponse:
    db = request.app.state.db
    # novel_id + character_id 双层隔离：novel_id 由人物节点自身属性解析
    center = db.get_character_by_id_global(character_id)
    if center is None:
        raise HTTPException(status_code=404, detail="人物不存在")
    graph = db.get_subgraph(center["novel_id"], character_id)
    return GraphResponse(**graph)
```

```python
# api/health.py
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    try:
        request.app.state.db.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Neo4j 不可达")
    return {"status": "ok"}
```

> 说明：`characters.py` 用到 `Neo4jDB.get_character_by_id_global(character_id)`——按 UUID 全局查找并返回含 `novel_id` 的字典。在 Step 6 中补充到 db/neo4j.py。

- [ ] **Step 6: 给 db/neo4j.py 补充 `get_character_by_id_global`**

在 `get_character` 方法后追加：

```python
    def get_character_by_id_global(self, character_id: str) -> dict | None:
        """按 UUID 全局查找人物，返回 {id, novel_id, name, mention_count}。"""
        with self._driver.session() as session:
            record = session.run(
                """MATCH (p:Person {id: $character_id})
                   RETURN p.id AS id, p.novel_id AS novel_id, p.name AS name,
                          p.mention_count AS mention_count""",
                character_id=character_id,
            ).single()
            return dict(record) if record else None
```

- [ ] **Step 7: 写 main.py**

```python
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
```

- [ ] **Step 8: 运行全部测试确认通过**

```powershell
# 单元测试（默认）：期望全部通过
pytest
# 集成测试：期望通过（Neo4j 运行中）
pytest -m integration
```

期望：单元 5 个文件全绿；集成 8 个用例全绿（3 db + 5 api）

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/api.py backend/app/api backend/app/main.py backend/app/db/neo4j.py backend/tests/integration/test_api_neo4j.py
git commit -m "feat: API 层与 main 装配（上传/进度/搜索/1跳子图/健康检查）"
```

---

### Task 11: 前端脚手架（Vite + React + TS + api/types）

**Files:**
- Create: `frontend/`（Vite react-ts 模板）
- Create: `frontend/vite.config.ts`（代理）
- Create: `frontend/src/types.ts`（DTO + 薄转换层）
- Create: `frontend/src/api.ts`

**Interfaces:**
- Consumes: 后端 API（Task 10）
- Produces: `types.ts` 导出 `JobStatus/JobProgress/FailedBlock/JobResponse/NovelResponse/CharacterCandidate/Evidence/GraphNode/GraphEdge/GraphResponse/ForceNode/ForceLink` 与 `toForceGraph(g: GraphResponse) -> {nodes, links}`；`api.ts` 导出 `uploadNovel(file)`、`getJob(jobId)`、`getNovel(novelId)`、`searchCharacters(novelId, q)`、`getGraph(characterId)`

- [ ] **Step 1: 创建工程**

```powershell
cd E:\CodeField\Long-Novel-Intelligence
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-force-graph-2d
```

- [ ] **Step 2: 配置 vite.config.ts（代理）**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

- [ ] **Step 3: 写 src/types.ts**

```ts
export type JobStatus = "pending" | "running" | "completed" | "completed_with_errors" | "failed";

export interface JobProgress {
  done_chunks: number;
  total_chunks: number;
}

export interface FailedBlock {
  chunk_id: number;
  chapter_id: number;
  error: string;
}

export interface JobResponse {
  job_id: string;
  novel_id: string;
  status: JobStatus;
  progress: JobProgress;
  failed_blocks: FailedBlock[];
  stats: Record<string, number>;
  error?: string | null;
}

export interface NovelResponse {
  id: string;
  title: string;
  chapters: { id: number; title: string }[];
  stats: Record<string, number>;
}

export interface CharacterCandidate {
  id: string;
  name: string;
  mention_count: number;
}

export interface Evidence {
  chunk_id: number;
  chapter_id: number;
  chapter_title: string;
  text: string;
}

export interface GraphNode {
  id: string;
  name: string;
  mention_count: number;
  is_center: boolean;
}

export interface GraphEdge {
  source_id: string;
  target_id: string;
  type: string;
  weight: number;
  confidence: number;
  evidence: Evidence[];
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---- 薄转换层：force-graph 内部状态与后端 DTO 隔离 ----

export interface ForceNode {
  id: string;
  name: string;
  mention_count: number;
  isCenter: boolean;
}

export interface ForceLink {
  source: string;
  target: string;
  type: string;
  weight: number;
  confidence: number;
  evidence: Evidence[];
}

export function toForceGraph(g: GraphResponse): { nodes: ForceNode[]; links: ForceLink[] } {
  const nodes: ForceNode[] = g.nodes.map((n) => ({
    id: n.id,
    name: n.name,
    mention_count: n.mention_count,
    isCenter: n.is_center,
  }));
  const links: ForceLink[] = g.edges.map((e) => ({
    source: e.source_id,
    target: e.target_id,
    type: e.type,
    weight: e.weight,
    confidence: e.confidence,
    evidence: e.evidence,
  }));
  return { nodes, links };
}
```

- [ ] **Step 4: 写 src/api.ts**

```ts
import type { CharacterCandidate, GraphResponse, JobResponse, NovelResponse } from "./types";

async function handle<T>(resp: Response | Promise<Response>): Promise<T> {
  const r = await resp;
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    throw new Error((body && body.detail) || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export async function uploadNovel(file: File): Promise<{ novel_id: string; job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return handle(fetch("/api/novels", { method: "POST", body: form }));
}

export function getJob(jobId: string): Promise<JobResponse> {
  return handle(fetch(`/api/jobs/${jobId}`));
}

export function getNovel(novelId: string): Promise<NovelResponse> {
  return handle(fetch(`/api/novels/${novelId}`));
}

export function searchCharacters(novelId: string, q: string): Promise<CharacterCandidate[]> {
  return handle(fetch(`/api/novels/${novelId}/characters?q=${encodeURIComponent(q)}`));
}

export function getGraph(characterId: string): Promise<GraphResponse> {
  return handle(fetch(`/api/characters/${characterId}/graph`));
}
```

- [ ] **Step 5: 验证**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\frontend
npm run build     # 期望 TypeScript 编译通过、产物生成到 dist/
```

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: 前端脚手架（Vite+React+TS/API 封装/薄转换层）"
```

---

### Task 12: 前端组件 Upload + Progress + App 状态流

**Files:**
- Create: `frontend/src/components/Upload.tsx`
- Create: `frontend/src/components/Progress.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `api.ts` 的 `uploadNovel` / `getJob`；`types.ts` 的 `JobResponse`
- Produces: `Upload`（props `onUploaded(novelId, jobId)`）、`Progress`（props `jobId` / `onDone(job: JobResponse)`）、`App`（上传→处理→选人→出图 的状态机；phase: upload/processing/graph）

- [ ] **Step 1: 写 Upload.tsx**

```tsx
import { useRef, useState } from "react";
import { uploadNovel } from "../api";

interface Props {
  onUploaded: (novelId: string, jobId: string) => void;
}

export default function Upload({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".epub")) {
      setError("仅支持 .epub 文件");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const { novel_id, job_id } = await uploadNovel(file);
      onUploaded(novel_id, job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div
        style={{ border: "2px dashed #999", borderRadius: 8, padding: 40, textAlign: "center", cursor: "pointer" }}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleFile(e.dataTransfer.files?.[0]);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".epub"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
        {busy ? "上传中…" : "拖拽或点击上传 .epub 小说"}
      </div>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: 写 Progress.tsx（固定 1s 轮询，只显示 done/total + 百分比）**

```tsx
import { useEffect, useState } from "react";
import { getJob } from "../api";
import type { JobResponse } from "../types";

const TERMINAL: string[] = ["completed", "completed_with_errors", "failed"];

interface Props {
  jobId: string;
  onDone: (job: JobResponse) => void;
}

export default function Progress({ jobId, onDone }: Props) {
  const [job, setJob] = useState<JobResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const j = await getJob(jobId);
        if (cancelled) return;
        setJob(j);
        if (TERMINAL.includes(j.status)) {
          clearInterval(timer);
          onDone(j);
        }
      } catch {
        /* 轮询瞬时错误忽略，下一轮重试 */
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, onDone]);

  if (!job) return <p>正在分析小说…</p>;

  const { done_chunks, total_chunks } = job.progress;
  const pct = total_chunks > 0 ? Math.round((done_chunks / total_chunks) * 100) : 0;

  return (
    <div>
      <p>
        正在分析小说：{done_chunks} / {total_chunks} chunks · {pct}%
      </p>
      <div style={{ width: "100%", background: "#eee", borderRadius: 4, height: 12 }}>
        <div style={{ width: `${pct}%`, background: "#4caf50", height: 12, borderRadius: 4 }} />
      </div>
      {job.status === "completed_with_errors" && (
        <p style={{ color: "orange" }}>{job.failed_blocks.length} 个文本块抽取失败，已跳过</p>
      )}
      {job.status === "failed" && <p style={{ color: "red" }}>分析失败：{job.error ?? "未知错误"}</p>}
    </div>
  );
}
```

- [ ] **Step 3: 写 App.tsx（状态流）**

```tsx
import { useState } from "react";
import CharacterSearch from "./components/CharacterSearch";
import GraphView from "./components/GraphView";
import Progress from "./components/Progress";
import Upload from "./components/Upload";
import type { CharacterCandidate, JobResponse } from "./types";

type Phase = "upload" | "processing" | "graph";

export default function App() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [novelId, setNovelId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [center, setCenter] = useState<CharacterCandidate | null>(null);

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h1>长篇小说知识图谱分析系统</h1>

      {phase === "upload" && (
        <Upload
          onUploaded={(nid, jid) => {
            setNovelId(nid);
            setJobId(jid);
            setJob(null);
            setCenter(null);
            setPhase("processing");
          }}
        />
      )}

      {phase === "processing" && jobId && (
        <Progress
          jobId={jobId}
          onDone={(j) => {
            setJob(j);
            if (j.status === "failed") setPhase("upload");
            else setPhase("graph");
          }}
        />
      )}

      {phase === "graph" && novelId && job && (
        <section>
          <p>
            人物 {job.stats?.persons ?? "?"} · 关系 {job.stats?.relationships ?? "?"}
            {job.status === "completed_with_errors" && `（${job.failed_blocks.length} 块失败已跳过）`}
          </p>
          <CharacterSearch novelId={novelId} onSelect={(c) => setCenter(c)} />
          {center ? (
            <GraphView
              characterId={center.id}
              onCenterChange={(id) => setCenter({ id, name: "" } as CharacterCandidate)}
            />
          ) : (
            <p style={{ color: "#888" }}>搜索并选择一个人物，查看其关系网络。</p>
          )}
          <button onClick={() => setPhase("upload")}>上传新小说</button>
        </section>
      )}
    </main>
  );
}
```

- [ ] **Step 5: 创建占位组件并验证编译**

Task 13 才实现 `CharacterSearch` / `GraphView`，本任务先创建占位组件保证 build 通过：

```tsx
// src/components/CharacterSearch.tsx（占位，Task 13 完整实现）
export default function CharacterSearch(_props: { novelId: string; onSelect: (c: { id: string; name: string }) => void }) {
  return <p>人物搜索（待实现）</p>;
}
```

```tsx
// src/components/GraphView.tsx（占位，Task 13 完整实现）
export default function GraphView(_props: { characterId: string; onCenterChange: (id: string) => void }) {
  return <p>关系图（待实现）</p>;
}
```

```powershell
cd E:\CodeField\Long-Novel-Intelligence\frontend
npm run build
```

期望：TypeScript 编译通过

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: 前端上传/进度组件与 App 状态流"
```

---

### Task 13: 前端组件 CharacterSearch + GraphView（关系图）

**Files:**
- Modify: `frontend/src/components/CharacterSearch.tsx`（替换占位）
- Modify: `frontend/src/components/GraphView.tsx`（替换占位）

**Interfaces:**
- Consumes: `api.ts` 的 `searchCharacters` / `getGraph`；`types.ts` 的 `toForceGraph` / `ForceNode` / `ForceLink` / `Evidence`
- Produces: `CharacterSearch`（props `novelId` / `onSelect(c: CharacterCandidate)`，300ms 防抖联想下拉）、`GraphView`（props `characterId` / `onCenterChange(id)`；force-graph 渲染，节点大小∝mention_count、中心高亮、边按 type 着色、点击节点切换中心、点击边显示 evidence 侧栏）

- [ ] **Step 1: 写 CharacterSearch.tsx**

```tsx
import { useEffect, useRef, useState } from "react";
import { searchCharacters } from "../api";
import type { CharacterCandidate } from "../types";

interface Props {
  novelId: string;
  onSelect: (c: CharacterCandidate) => void;
}

export default function CharacterSearch({ novelId, onSelect }: Props) {
  const [q, setQ] = useState("");
  const [candidates, setCandidates] = useState<CharacterCandidate[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!q.trim()) {
      setCandidates([]);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const list = await searchCharacters(novelId, q.trim());
        setCandidates(list);
        setOpen(true);
      } catch {
        setCandidates([]);
      }
    }, 300);
    return () => window.clearTimeout(timer.current);
  }, [q, novelId]);

  return (
    <div style={{ marginBottom: 12 }}>
      <input
        style={{ width: 320, padding: 8, fontSize: 14 }}
        placeholder="输入人物名…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {open && candidates.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, border: "1px solid #ccc", maxWidth: 320 }}>
          {candidates.map((c) => (
            <li
              key={c.id}
              style={{ padding: 8, cursor: "pointer" }}
              onClick={() => {
                setOpen(false);
                onSelect(c);
              }}
            >
              {c.name}（出现 {c.mention_count} 块）
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 写 GraphView.tsx**

```tsx
import { useEffect, useMemo, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { getGraph } from "../api";
import { toForceGraph } from "../types";
import type { Evidence, ForceLink, ForceNode, GraphResponse } from "../types";

interface Props {
  characterId: string;
  onCenterChange: (id: string) => void;
}

const TYPE_COLORS: Record<string, string> = {
  love: "#e91e63",
  family: "#9c27b0",
  friendship: "#2196f3",
  enmity: "#f44336",
  alliance: "#4caf50",
  mentorship: "#ff9800",
  other: "#9e9e9e",
};

export default function GraphView({ characterId, onCenterChange }: Props) {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<ForceLink | null>(null);

  useEffect(() => {
    let cancelled = false;
    getGraph(characterId).then((g) => {
      if (!cancelled) {
        setGraph(g);
        setSelectedEdge(null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [characterId]);

  const data = useMemo(() => (graph ? toForceGraph(graph) : null), [graph]);

  if (!data) return <p>加载关系图…</p>;

  return (
    <div style={{ display: "flex", height: 600 }}>
      <div style={{ flex: 1 }}>
        <ForceGraph2D
          graphData={{ nodes: data.nodes, links: data.links }}
          nodeId="id"
          nodeLabel={(n: ForceNode) => `${n.name}（${n.mention_count} 块）`}
          nodeVal={(n: ForceNode) => Math.max(3, Math.log2(n.mention_count + 1) * 4)}
          nodeColor={(n: ForceNode) => (n.isCenter ? "#ff5722" : "#607d8b")}
          linkColor={(l: ForceLink) => TYPE_COLORS[l.type] ?? "#999"}
          linkWidth={(l: ForceLink) => Math.min(6, 1 + Math.log2(l.weight + 1))}
          onNodeClick={(n: ForceNode) => {
            if (!n.isCenter) onCenterChange(n.id);
          }}
          onLinkClick={(l: ForceLink) => setSelectedEdge(l)}
        />
      </div>
      {selectedEdge && (
        <div style={{ width: 300, padding: 8, overflow: "auto", borderLeft: "1px solid #ccc" }}>
          <h4>
            {selectedEdge.type} · weight {selectedEdge.weight} · 置信度{" "}
            {selectedEdge.confidence.toFixed(2)}
          </h4>
          {selectedEdge.evidence.map((e: Evidence, i: number) => (
            <div key={i} style={{ marginBottom: 8, fontSize: 13 }}>
              <strong>
                第{e.chapter_id}章 {e.chapter_title}
              </strong>
              <p style={{ whiteSpace: "pre-wrap", maxHeight: 120, overflow: "auto" }}>{e.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 验证**

```powershell
cd E:\CodeField\Long-Novel-Intelligence\frontend
npm run build
```

期望：TypeScript 编译通过

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat: 人物搜索联想与关系图渲染（切换中心/evidence 侧栏）"
```

---

### Task 14: 端到端手工验收 + README 完善

**Files:**
- Modify: `README.md`
- 无新代码

**Interfaces:**
- Consumes: 全部已完成模块

- [ ] **Step 1: 启动全栈**

```powershell
cd E:\CodeField\Long-Novel-Intelligence
docker compose up -d neo4j
# 后端
cd backend
cp ../.env.example .env   # 填入真实 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
uvicorn app.main:app --reload --port 8000
# 前端（另开终端）
cd frontend
npm run dev
```

- [ ] **Step 2: 手工验收清单**

1. 打开 http://localhost:5173，拖拽上传一部公版小说 .epub（如《红楼梦》）
2. 上传后显示进度条：`x / y chunks · z%`，1s 刷新；结束后显示「人物 n · 关系 m」
3. 输入「贾宝玉」出现联想候选（含出现块数），点选后渲染关系图：中心节点橙色、其余灰色，节点大小随 mention_count 变化
4. 悬浮边显示 type/weight/confidence；点击边，侧栏出现 evidence（章节标题 + 原文片段）
5. 点击非中心节点，关系图切换为该人物为中心的 1 跳子图
6. 上传非 epub 文件 → 报「仅支持 .epub 文件」
7. 停掉 Neo4j 后点上传 → 报「Neo4j 不可达」
8. 浏览器 DevTools Network 中确认轮询间隔约 1s、无 WebSocket

- [ ] **Step 3: 完善 README.md**

在 README 末尾追加「验收记录」小节：

```markdown
## 验收记录（V0.1）

- [ ] 上传 .epub → 进度条（1s 轮询）→ 统计
- [ ] 搜索人物 → 1 跳关系图（中心高亮/边着色/evidence 侧栏）
- [ ] 点击节点切换中心人物
- [ ] 非 epub 文件被拒绝（400）
- [ ] Neo4j 停止时上传返回 503
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: V0.1 验收清单与已知限制"
```

---

## Self-Review（已执行）

**Spec 覆盖核对**：
- §3 数据模型（Novel/Person/RELATES_TO、weight/confidence/evidence 语义、两个唯一约束、novel_id 隔离）→ Task 6（聚合语义）、Task 9（约束/写入/查询）
- §4 管线（epub→章节→切块→强制结构化→Pydantic→merger）→ Task 3/4/5/6/7；失败分类与重试 → Task 7；并发配置化 → Task 7 + Task 2（LLM_CONCURRENCY）
- §5 API（6 个端点、Job 状态枚举、内存 JobStore、1 跳子图）→ Task 8/10
- §6 前端（上传/进度/搜索/图、薄转换层、1s 轮询）→ Task 11/12/13
- §7 配置 → Task 2 + .env.example（Task 1）
- §8 错误处理 → Task 10（400/413/503/404、启动校验）
- §9 测试（unit 默认 / integration marker）→ Task 1 conftest + 各测试任务
- §10 目录结构 → 各任务文件清单一致
- §11 非目标 → 无实现

**占位符扫描**：无 TBD/TODO；Task 12 的占位组件在 Task 13 完整替换，非计划占位。

**类型一致性核对**：`Chunk`/`Chapter`/`ExtractionResult`/`MergedGraph`/`RelAgg`（weight/confidence 属性）/`JobState`/`JobResponse.from_state`/`Neo4jDB` 各方法签名/前端 `ForceNode`/`ForceLink`/`toForceGraph` 在跨任务引用中签名一致；`extract_all` 的 `on_chunk_done` 参数在 Task 7 定义、Task 10 使用一致；`get_character_by_id_global` 在 Task 10 Step 6 补齐并被 characters.py 使用，无悬空引用。
