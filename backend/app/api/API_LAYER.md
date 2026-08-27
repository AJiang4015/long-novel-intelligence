# API_LAYER.md — api 层契约与边界

> 定位：**Layer Contract / Layer Boundary**（本层负责什么、不能负责什么），不是代码使用说明。
> 全局架构见 `../../../ARCHITECTURE.md`；编排所调用的业务决策归属见 `../pipeline/PIPELINE_LAYER.md`。

## 1. Responsibility

HTTP 边界与 ingest 编排：

- 端点：`POST /api/novels`（上传 EPUB + 后台 ingest）、`GET /api/jobs/{job_id}`、`GET /api/novels/{novel_id}`、`GET /api/novels/{novel_id}/characters?q=`、`GET /api/characters/{character_id}/graph`、`GET /api/health`
- 编排：`novels.py:_run_ingest`（epub → chunk → extract → resolve → merge → write → job 更新）
- DTO 转换：请求/响应 ↔ `schemas/api.py`

## 2. Input contract

- multipart `.epub`（≤50MB，超限拒绝）
- 路径/查询参数（novel_id / character_id / q）

## 3. Output contract

- JSON DTO（`schemas/api.py`：`NovelCreateResponse` / `JobResponse` / `NovelResponse` / `CharacterCandidate` / `EvidenceItem` 等）
- 副作用：写库（经 `db` 层）、job 状态更新（经 `models` 层）
- 错误：HTTPException 映射（400 非 epub / 404 不存在 / 503 Neo4j 不可用）

## 4. Decision ownership

- 端点契约、状态码、参数校验
- ingest 编排顺序（流水线各阶段的调用次序与 job 进度更新）
- job 终态映射（completed / completed_with_errors / failed）

## 5. Allowed dependencies

- `config`（Settings，进程内缓存）
- `db`（Neo4jDB）
- `models`（JobStore / JobStatus）
- `pipeline`（epub_reader / chunker / extractor / resolver / merger / lineage / llm_client）
- `schemas`（DTO）

## 6. Forbidden dependencies

- 不直接写 cypher（经 `db` 层）
- 不实现 ER 判定 / 合并决策 / mention 分类 / role gate（属 pipeline）
- 不构造 LLM prompt 语义（prompt 属 pipeline）

## 7. Invariants

- API / DTO 向后兼容（修改需按 `../../../AGENTS.md` §2 规则评审；已有稳定端点不因 UI 需求改动）
- Neo4j 不可用时上传返回 503
- 上传校验先于 ingest 启动（非 epub / 超限拒绝）
- 端点不返回内部异常细节（LLM key 等敏感信息不落响应）

## 8. Failure ownership

- 端点级异常 → HTTPException（404/400/503）
- ingest 内部失败（LLM 失败块 / 解析失败）→ job `failed_blocks` + 状态；P11（全 chunk 失败 → failed）**尚未实现**（见 `../../../PROBLEM.md` P11），状态机规则若立项归 `models` 层（`../models/MODEL_LAYER.md` §4）
- 请求级失败不污染业务数据（数据库操作全程走 `db` 层隔离）

## 9. Testing expectations

- integration：`tests/integration/test_api_neo4j.py`（独立 novel_id 自建自清，需 novel-neo4j 运行中）
- unit：路由/DTO 校验逻辑（全 mock，无网络）
- 不得在测试中清空数据库（`../../../TESTING.md` §1）

## 10. Typical changes allowed here

- 新增端点 / 查询参数 / DTO 字段（向后兼容）
- ingest 编排顺序调整（阶段调用次序，不改变各层内部决策）
- 校验规则（大小/类型/格式）

## 11. Changes that must be implemented elsewhere

- ER / 合并 / 分类决策：→ `pipeline`（`../pipeline/PIPELINE_LAYER.md`）
- 写库 / 事务 / 删除：→ `db`（`../db/DB_LAYER.md`）
- 契约类型与枚举：→ `schemas`（`../schemas/SCHEMA_LAYER.md`）
- job 状态机规则：→ `models`（`../models/MODEL_LAYER.md`）
