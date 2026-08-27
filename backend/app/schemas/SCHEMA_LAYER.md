# SCHEMA_LAYER.md — schemas 层契约与边界

> 定位：**Layer Contract / Layer Boundary**（本层负责什么、不能负责什么），不是代码使用说明。
> 全局架构见 `../../../ARCHITECTURE.md`；契约语义被 pipeline 与 api 依赖。

## 1. Responsibility

跨层数据契约定义：

- `schemas/llm.py`：LLM 契约类型——`MentionCategory`（PERSON/GENERIC/COLLECTIVE/DESCRIPTIVE/COMPOSITE/INVALID）、`Character`、`Relationship`、`ExtractionResult`、`AliasCandidate`、`PendingMention`、`AliasJudgeResult` 等
- `schemas/api.py`：HTTP DTO——`NovelCreateResponse` / `NovelListItem` / `JobResponse` / `NovelResponse` / `CharacterCandidate` / `EvidenceItem` 等

## 2. Input contract

- 无外部输入；类型被 api / pipeline 层 import

## 3. Output contract

- 类型定义 + pydantic 校验（字段约束 / 模型校验）

## 4. Decision ownership

- 字段约束：name `min_length=1, max_length=50`；confidence `[0.0, 1.0]`
- 枚举语义：`MentionCategory` 是 extract 契约输出（LLM 未输出时 `None` 是合法值，走 hygiene 兜底）
- 模型校验：`ExtractionResult` self-loop 直接丢弃
- 枚举值稳定性（下游逻辑依赖 `.value` 字符串，见 lineage 字段约定）

## 5. Allowed dependencies

- pydantic（BaseModel / Field / model_validator）
- `schemas/api.py` 可依赖 `models`（复用 `JobState` / `JobStatus` / `FailedBlock`）
- `schemas/llm.py` 保持独立（不依赖任何层）

## 6. Forbidden dependencies

- 不依赖 pipeline / db / api
- 不承载业务逻辑（决策逻辑一律在 pipeline；校验之外不做语义判定）

## 7. Invariants

- 契约稳定：修改 API / DTO 需向后兼容（`../../../AGENTS.md` §2）
- 枚举值稳定（新增枚举需评审）；`MentionCategory` 的 None 语义不可破坏
- 校验规则确定（self-loop 丢弃等）

## 8. Failure ownership

- 校验失败 → pydantic `ValidationError`（api 层映射 4xx；config 层映射启动错误）
- 契约变更导致的下游破坏 → 本层负责兼容性评估

## 9. Testing expectations

- 模型校验单测（字段边界 / 枚举 / self-loop）
- 变更后跑相关 unit（`test_llm_client` 等间接覆盖）与 api integration

## 10. Typical changes allowed here

- 新增 DTO / 字段（向后兼容，旧字段不删）
- 新增校验规则（不破坏既有合法输入）
- 新增枚举值（需评审：影响 lineage 事件字段、hygiene/resolver 决策表）

## 11. Changes that must be implemented elsewhere

- 分类 / 判定 / 合并决策：→ `pipeline`（`../pipeline/PIPELINE_LAYER.md`）
- 状态机：→ `models`（`../models/MODEL_LAYER.md`）
- HTTP 端点行为：→ `api`（`../api/API_LAYER.md`）
