# MODEL_LAYER.md — models 层契约与边界

> 定位：**Layer Contract / Layer Boundary**（本层负责什么、不能负责什么），不是代码使用说明。
> 全局架构见 `../../../ARCHITECTURE.md`。

## 1. Responsibility

进程内领域状态模型（`models/job.py`）：

- 任务生命周期状态机：`JobStatus`（pending / running / completed / completed_with_errors / failed）
- 任务存储：`JobStore`（进程内，threading.Lock 保证线程安全）
- 状态载体：`JobState` / `FailedBlock`

## 2. Input contract

- job 操作：`create(job_id, novel_id)` / `get` / `update` / `increment_done` 等

## 3. Output contract

- `JobState`（状态 + done/total chunks + failed_blocks + stats + error）
- 供 `schemas/api.py` 复用（`JobResponse.from_state` 映射）

## 4. Decision ownership

- job 状态机合法转换规则（pending → running → completed / completed_with_errors / failed）
- P11（全部 chunk 失败 → failed）：该规则**尚未实现**（`../../../PROBLEM.md` P11，代码变更未授权）；若立项实现，状态机规则归属本层
- 失败块记录语义（FailedBlock 列表）

## 5. Allowed dependencies

- pydantic（BaseModel / Field）
- threading（Lock）

## 6. Forbidden dependencies

- 不 import pipeline / LLM / db / api
- 不持久化（进程内存储，重启丢失 = 已知限制，未来独立立项替换）

## 7. Invariants

- 状态机只允许合法转换；非法转换应被拒绝
- 进程内存储：进程重启后任务丢失（已知限制，`../../../DECISIONS.md` D-14）
- 线程安全（Lock 保护共享字典）

## 8. Failure ownership

- 状态机非法转换 / 并发读写 → 本层防御（Lock / 校验）
- 重启丢失 → 已知限制，不是 bug（D-14）

## 9. Testing expectations

- unit：`tests/unit/test_job_store.py`（全 mock，无网络/Neo4j）

## 10. Typical changes allowed here

- 状态字段扩展 / 状态机规则调整（P11 类修复）
- 未来替换为持久化任务存储（独立立项，影响 api 层使用方式）

## 11. Changes that must be implemented elsewhere

- 业务结果判定（抽取/消歧/合并结果）：→ `pipeline`（`../pipeline/PIPELINE_LAYER.md`）
- 写库持久化：→ `db`（`../db/DB_LAYER.md`）
- HTTP 暴露：→ `api`（`../api/API_LAYER.md`）
