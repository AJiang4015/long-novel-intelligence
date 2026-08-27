# ARCHITECTURE.md — Long-Novel-Intelligence 系统架构

> 定位：**系统怎么组织**——整体结构、数据流、依赖方向、核心边界。
> 本文是全局架构地图，**不是**逐文件代码说明；每层细节见对应 `*_LAYER.md`（`backend/app/*/XXX_LAYER.md`）。
> 规则（必须遵守什么）见 `AGENTS.md`；任务怎么做见 `PROCESS.md`。

---

## 0. 项目概述与技术栈

基于 EPUB 长篇小说进行人物实体抽取、实体消歧、人物关系构建与关系图可视化。

| 栈 | 选型 |
|---|---|
| Backend | FastAPI + Python |
| Frontend | React + Vite + TypeScript |
| Graph database | Neo4j Community 5.26.x（独立容器 `novel-neo4j`） |
| LLM | 阿里百炼 OpenAI 兼容接口（`BAILIAN_URL` / `BAILIAN_MODEL`） |
| Frontend graph rendering | custom SVG GraphCanvas |
| Deployment | backend/frontend 本地开发 + 独立 Neo4j Docker 容器 |

---

## 1. 数据流（端到端）

```text
EPUB (.epub, ≤50MB)
 ↓
API / ingestion orchestration（backend/app/api/novels.py `_run_ingest`，后台 job）
 ↓
epub_reader（EPUB → chapters）
 ↓
sections（章节 section 分类：METADATA / EPIGRAPH / BODY / TRAILER）
 ↓
chunker（按 CHUNK_SIZE / CHUNK_OVERLAP 切块）
 ↓
extractor（并发 LLM 抽取：characters + relationships；concurrency 来自配置）
 ↓
hygiene（deterministic hard filter：COLLECTIVE / INVALID 直滤）
 ↓
resolver（EntityResolver：recall → judge → admission → registration；
         role gate / provisional / deferred / unresolved；整本一个实例）
 ↓
merger（跨 chunk 聚合 → merge decision(b1, 纯内存) → merge apply(b2)）
 ↓
db / Neo4j（upsert_graph 单事务写入；按 novel_id 隔离；仅 Novel / Person / RELATES_TO）
 ↓
API response（characters 查询 / 关系图 / job 状态 / 健康检查）
```

## 2. 层与模块职责

| 层 | 模块 | 职责 | 细节 |
|---|---|---|---|
| `api/` | novels / characters / jobs / health | HTTP 边界、DTO 转换、ingest 编排、job 状态暴露 | [API_LAYER.md](backend/app/api/API_LAYER.md) |
| `db/` | neo4j.py | Neo4j 访问封装、novel_id 隔离读写、约束、单事务写入、`delete_novel` | [DB_LAYER.md](backend/app/db/DB_LAYER.md) |
| `models/` | job.py | 进程内任务状态机（JobStore / JobState / JobStatus） | [MODEL_LAYER.md](backend/app/models/MODEL_LAYER.md) |
| `pipeline/` | epub_reader / sections / chunker / llm_client / extractor / hygiene / resolver / merger / lineage | 抽取、消歧、合并、观测全链路 | [PIPELINE_LAYER.md](backend/app/pipeline/PIPELINE_LAYER.md) |
| `schemas/` | api.py / llm.py | 跨层数据契约（DTO / MentionCategory / ExtractionResult） | [SCHEMA_LAYER.md](backend/app/schemas/SCHEMA_LAYER.md) |
| 根 | config.py / main.py | 配置（进程内缓存）、FastAPI 组装（lifespan 初始化全局依赖） | — |

## 3. 依赖方向（代码事实）

```text
main.py ──组装──▶ api 路由
api      ──▶ pipeline / db / models / schemas / config
pipeline ──▶ schemas（契约类型）
schemas  ──▶ models（仅 schemas/api.py 复用 JobState/JobStatus）
db       ──▶ neo4j driver（唯一外部依赖）
models   ──▶ 无（pydantic + threading）
```

- 允许方向：`api → pipeline`、`api → db`、`api → models`、`api → schemas`、`api → config`、`pipeline → schemas`、`schemas → models`。
- **不允许反向依赖**：pipeline / db / models 不得 import api；db / models 不得 import pipeline。

## 4. 边界规则（禁止跨层实现）

- **api 层**不得实现 ER 判定、合并决策、mention 分类、LLM prompt——只做编排与转换。
- **pipeline 层**不得直接访问 Neo4j、不得接触 HTTP；数据经 `db` 层持久化。
- **db 层**不得做业务决策（canonical 选择、合并判断、role 判定）；只执行按 novel_id 隔离的读写。
- **models 层**不得依赖 pipeline / LLM / db；不承载业务结果判定。
- **lineage** 是纯旁路 observer：不得参与任何业务判定、不得修改 resolver/extraction 输出、不得改变 merge 行为。
- 层内具体「owns / does NOT own」见各 `*_LAYER.md`；违规修改先读 `AGENTS.md` §2 与对应 Layer 文档。

## 5. 数据进出：在哪里转换、在哪里持久化

| 阶段 | 位置 | 说明 |
|---|---|---|
| 进入 | `api/novels.py` | EPUB 上传（multipart，≤50MB），生成 novel_id + job_id |
| 转换 | `pipeline/` | EPUB→chapters→chunks→extraction→resolved graph→merged graph（全程内存） |
| 持久化 | `db/neo4j.py` | 最终图单事务写入 Neo4j（Novel / Person / RELATES_TO） |
| 读取 | `api/characters.py` / `api/novels.py` | 经 `db` 层查询，按 novel_id（+ character_id 双层）隔离 |

## 6. 与其它文档的关系

| 文档 | 关系 |
|---|---|
| `AGENTS.md` | 硬规则与边界红线（违反即导致项目不正确）；§0 文档地图 |
| `PROCESS.md` | 任务流程与实验纪律 |
| `DECISIONS.md` | 本架构中已做出的长期决策及其理由（D-2 身份模型 / D-3 数据模型边界 / D-13 职责边界等） |
| `*_LAYER.md` | 每层契约的 11 点明细（本文件只保留全局地图） |
| `PROBLEM.md` | 问题地图 + 诊断路由（层归属的归因入口） |
