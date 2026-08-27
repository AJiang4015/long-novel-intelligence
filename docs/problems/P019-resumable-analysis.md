# P019 — Ingest 任务不可恢复，中断后重跑重复消耗 LLM token（Resumable Analysis / Checkpointed Pipeline）

- **Status**: ✅ implemented（代码 + 测试完成并提交 `d726d2f`）；真实评估完成（Run 5，qwen3.8-flash）——见 §18 / [评估报告](../evaluation/2026-08-28-biancheng-p19-resume-eval.md)
- **Severity**: High（token 成本 + 可靠性）
- **Domain**: 流程 / pipeline 可靠性 / 基础设施
- **Tags**: checkpoint, resume, idempotency, token-cost, job-recovery, durable-state
- **First Seen**: V0.1（D-14 记录「进程重启后任务丢失」）；真实触发于历次真实评估环境（P04 欠费 / P05 限流 / 进程中断后重传）
- **Last Verified**: 2026-08-28（代码审计确认：extraction/judge 中间结果无任何持久化；JobStore 纯进程内）
- **Evidence Level**: HIGH（代码事实，可复现）
- **Decision Type**: FACT（代码现状）+ DESIGN_DECISION（P19 修复方向已定，见 Spec）
- **Related Problems**: P04（欠费触发大批失败）/ P05（429 限流）/ P11（全 chunk 失败终态语义，交互但不在本任务修复）/ P13（脚本被杀/超时经验）/ P14（Neo4j 属性类型限制——排除 Neo4j 作 checkpoint 存储的依据之一）
- **Related Commits**: 未实现（无）
- **Related Evaluation Reports**: 无直接报告；触发场景来自历次真实评估事故记录（P04/P05/P13）

## 1. Context

一次小说分析消耗大量 token：抽取阶段每 chunk 一次 LLM 调用（输入=整块正文，~4000 字符≈4000+ token），judge 阶段每 chunk 至多一次（**输入同样包含整块 chunk 正文** + mentions），末尾一次 merge judge。长篇小说 200+ chunk 量级 → 单次 ingest 输入 token 达百万级。

当前流程中：chunk 已分析成功，但 job 中途因 token quota / 网络 / 进程异常失败后，**已完成 chunk 没有任何持久化恢复能力**——重跑会重复消耗全部 token。

## 2. Symptom

- job 中途失败（token quota / 网络 / 进程崩溃重启）后，用户重传同一 EPUB：
  - `POST /api/novels` 生成**全新 novel_id**（uuid4）；
  - 全部 chunk 重新 `extract_chunk` + 重新 `judge_aliases`；
  - 已完成 chunk 的分析结果**全部作废**。
- 进程崩溃后 `GET /api/jobs/{old_job_id}` 404（JobStore 内存态，D-14 已知限制）。

## 3. Impact

- 每中断一次浪费 ≈ 已完成部分的「抽取输入（每 chunk 整块正文）+ judge 输入（每 chunk 再次整块正文）」token。
- 长篇小说中断于 50% ≈ 浪费约一半 ingest 输入 token（百万级输入 token 量级）。
- token quota 场景最恶劣：quota 耗尽 → 大批失败 → 用户充值后重传 → 全量重跑，即使重跑前已完成大部分 chunk。
- 与 P11 交互：全 chunk 失败时 job 终态为 `completed_with_errors`（P11 独立问题，本任务不修），用户看到「部分成功」但实际无数据。

## 4. Trigger

- job 中途因 token quota / 网络 / 进程异常失败，随后重传同一 EPUB 或重启后端。
- 进程崩溃重启后，旧 job_id 消失（D-14），只能重传。

## 5. Timeline

- **T1（V0.1）**：D-14 决策记录「JobStore 进程内存储；重启后任务丢失为已知限制，后续版本替换为持久化任务存储」。
- **T2（V0.2.x）**：历次真实评估中因 P04 欠费 / P05 限流 / 进程中断出现失败 job；每次重跑均从零开始。
- **T3（2026-08-28）**：立项 P19。代码审计确认无任何 checkpoint / resume / 中间结果持久化；确认修复方向（双层 checkpoint + 同文件自动续跑）；产出本 Record + Design Spec，待 Review。

## 6. Initial Hypothesis

「中断后只能完整重跑 pipeline」→ 设计阶段被推翻：resolver 是确定性的（PIPELINE_LAYER §7），给定相同的（chunk 文本、extraction 结果、judge 结果、chunk 顺序）可逐字节重放；因此**已完成阶段可以被持久化并在恢复时零 LLM 调用地重放**。

## 7. Investigation Path

```text
Step 1  代码审计 novels.py:_run_ingest 全链路
Step 2  审计 extractor.py：extract_all/extract_one 的失败分类与结果去向
Step 3  审计 resolver.py：judge 调用点、每 chunk 调用次数、确定性不变量
Step 4  审计 llm_client.py：三个 LLM 调用点的输入构成（judge 含 chunk 正文）
Step 5  审计 models/job.py + D-14：job 状态持久化现状
Step 6  审计 db/neo4j.py：已持久化内容（仅最终图，无中间结果）
Step 7  审计 lineage：raw extraction dump 是否可复用（结论：不可——debug 用途、默认关、无恢复语义）
```

## 8. Experiments

（设计阶段，尚未实施。计划中的验证实验见 §15 Validation 与 Spec §11/§13 测试矩阵；核心为 mock-LLM 失败注入 + resume 的零重复调用断言。）

## 9. Evidence

- **code evidence（novels.py）**：`_run_ingest` 一次函数跑完全链路；`extract_all` 结果只存 `ExtractionBundle`（内存）；`judge_aliases` / `judge_merges` 结果不落盘；`done_chunks` 仅进程内计数。
- **code evidence（extractor.py）**：`extract_all` 用 ThreadPoolExecutor 并发；每 chunk 成功/失败仅进入内存 `results` / `failed` 列表；无持久化钩子。
- **code evidence（resolver.py）**：`EntityResolver` 整本有状态（known/_index/canonical_aliases/_role_*）；每 chunk 至多一次 batch judge（D-17 B1 并入 deferred）；确定性不变量（chunk_id 升序、确定性 tie-break）已由 PIPELINE_LAYER §7 锁定。
- **code evidence（llm_client.py）**：`judge_aliases(chunk_text, pending)` 的 prompt 包含完整 chunk 正文 → **judge 重放可避免再次发送 chunk 正文**（token 收益的另一半）。
- **code evidence（job.py / DECISIONS.md D-14）**：`JobStore` 进程内 dict + Lock；注释与 D-14 明示「重启丢失为已知限制」。
- **code evidence（neo4j.py）**：仅 `upsert_novel`（标题+章节 JSON）+ `upsert_graph`（Person/RELATES_TO 单事务）；**无 chunk / extraction / judge 任何中间态**。
- **grep evidence**：`backend/app` 无 `resume` / `checkpoint` / `persist` / `restore` 任何实现痕迹。

## 10. Root Cause

中间产物（chunk 文本、extraction result、judge result、merge judge result）**无 durable 持久化**；job 与进度只存在于进程内（D-14）；`POST /api/novels` 每次生成全新 novel_id，无「同一内容」识别能力 → 中断后重传 = 全新分析 = 全量重跑。

## 11. Ruled-out Causes

- ~~Neo4j 可作为 checkpoint 存储~~：D-3 数据模型边界只允许 Novel / Person / RELATES_TO；新增标签/关系类型需独立设计决策；且 P14 记录 Neo4j 属性类型限制（map 需 JSON 序列化）——为最小改动排除。
- ~~持久化 JobStore 是必需前置~~：D-14 保持进程内；**durable recovery state 由 checkpoint 承担**，「Job 是 execution handle，Checkpoint 才是 recovery state」（用户拍板，见 §17）。
- ~~lineage raw extraction 可复用为 checkpoint~~：默认关闭、debug 用途、无版本/指纹校验、无恢复编排语义——用途不同，排除。

## 12. Failed Approaches

- 无（新立项；修复前无失败方案记录。设计阶段的排除项见 §11）。

## 13. Correct Approach

extraction + judge **双层文件 checkpoint** + 版本/输入指纹 + **同文件 sha256 自动续跑**：

- `POST /api/novels` 不变；以 EPUB sha256 为内容身份；仅当 sha256 + chunking version + extractor version + prompt version + model + schema version 等全部兼容时才复用 checkpoint；
- 命中未完成 checkpoint → **复用原 novel_id**，跳过所有 COMPLETED chunk，仅继续 PENDING/FAILED；
- 已完整完成的同文件再次上传 → **零 LLM 调用**（幂等返回既有 novel_id + 终态统计）；
- judge checkpoint identity = `chunk_id + judge_version + judge_input_fingerprint`（**不绑定 chunk_id alone**——同一 chunk 可能因候选集/resolver 状态变化产生多个 judge 输入）；
- job_id 进程内（D-14 不动）；novel_id 可被新 job 复用；checkpoint 为 durable source of truth。

详见 `docs/superpowers/specs/2026-08-28-p019-resumable-analysis-design.md`。

## 14. Invariants

- extraction / resolver / merge 的**语义规则零改动**（PIPELINE_LAYER 决策矩阵逐字节不变）；
- P16 / P17 / P18 冻结决策不重开（D-6 / D-9 / D-10 / D-13）；
- D-14 不 supersede（JobStore 保持进程内）；
- API / DTO 向后兼容；前端零改动；
- `er_checkpoint_enabled=False` 时行为与现状逐字节一致；
- 删除数据仍走 `db.delete_novel(novel_id)`（checkpoint 目录清理为伴生动作，不入 db 层）。

## 15. Validation

核心验收标准（P19 验收基准，用户指定）：

> **恢复任务时，所有 fingerprint 完全一致且状态为 COMPLETED 的 extraction/judge checkpoint 必须零 LLM 调用；只有不存在兼容 checkpoint 的阶段才能重新调用 LLM。**

- **确定性锁死**：全量运行 vs 中断后恢复运行的最终 MergedGraph **逐字节一致**（mock LLM 计数验证）；
- **幂等**：已完整完成的同文件重传 → 零 LLM 调用、返回同一 novel_id、job 立即终态；
- **失败重试**：FAILED chunk 在**每次恢复时重新尝试**（attempts 仅观测计数，**不熔断**——v1.1 删除 PERMANENT_FAILED），不触碰 COMPLETED chunk；单次 job 内失败由既有 FailedBlock → completed_with_errors 表达（P11 交互注明）；
- **指纹失效**：prompt / model / chunk 配置 / schema 任一变化 → 旧 checkpoint 不被复用（全新分析）；
- **judge 多输入**：同一 chunk 两次不同 pending → 两个独立 judge checkpoint，各自正确重放；
- 单元（全 mock）+ 集成（真实 Neo4j + mock LLM）见 Spec §13。

## 16. Trade-offs

- **磁盘占用**：checkpoint 持久化 chunk 全文 + 结果 JSON，量级 ≈ 小说文本体量（数 MB 级），可接受；
- **resume 依赖重传同一文件**：不持久化 epub 原件；用户丢失原文件则无法续跑（换新内容 = 新 novel_id = 全新分析，语义正确）；
- **版本兼容收紧**：prompt/model/配置任一变化即作废旧 checkpoint → 保守、防错复用，代价是实验性改动（如 A-1 Prompt A/B）天然不能复用旧 checkpoint（这正是 A-1 归因纪律需要的）；
- **失败不熔断**：FAILED chunk 每次 resume 都重新尝试（attempts 仅观测计数）——代价是 quota 长期未恢复时跨 resume 的重复尝试成本（每次 resume 每 FAILED chunk 1-2 次调用，**远小于全量重跑**）；与「resume 是可靠恢复机制」语义一致（transient 故障不永久封死 checkpoint）；

## 17. Decision（已确认设计选择，2026-08-28 用户拍板）

| # | 决策 | 内容 |
|---|---|---|
| 1 | resume 触发 | 重传同文件自动续跑；`POST /api/novels` 签名不变；**本阶段不新增 resume API** |
| 2 | 内容身份 | EPUB `sha256` 为内容身份；复用 checkpoint 需 sha256 + chunking_version + extractor_version + prompt_version + model + schema_version 全部兼容 |
| 3 | checkpoint 深度 | **extraction + judge 双层**；extraction 成功后立即持久化；judge 成功后立即持久化 |
| 4 | judge 身份 | `chunk_id + judge_version + judge_input_fingerprint`（非 chunk_id alone） |
| 5 | 分层 | job_id = 执行实例（进程内）；novel_id = 小说身份（可复用）；checkpoint = durable recovery state |
| 6 | 幂等 | 已完整完成的同文件重传零 LLM 调用 |
| 7 | 边界 | 不 supersede D-14；不引入持久化 JobStore；不新增 API；前端零改动；不改 P16/P17/P18 语义 |
| 8 | 流程 | Problem Record + Spec → Review → 实现（当前处于 Review Round 2 前） |

### Review Round 1 修订（2026-08-28，评审 10 条可靠性意见全部采纳）

| # | 修订 | 内容 |
|---|---|---|
| 1 | manifest 两态 | `IN_PROGRESS / COMPLETED`（无 FAILED）；异常终止保持 IN_PROGRESS = recoverable state；job 的 FAILED 是 execution state；损坏 manifest 视为不存在 |
| 2 | 删除熔断 | **无 PERMANENT_FAILED / attempts 熔断**：FAILED chunk 每次 resume 重新尝试；attempts 仅观测计数 |
| 3 | 幂等 job 语义 | 完整完成重传 → **不复活历史 job**，创建新的 terminal job（新 job_id，done_chunks=chunk_count，final_stats 复用，零 LLM） |
| 4 | TOCTOU 闭合 | `JobStore.get_or_create_running_job(novel_id)` 单锁临界区 check+create；AC-8：同内容并发上传最多一个非终态 job |
| 5 | index 并发 | 进程级锁 + read-modify-write + atomic rename；index 非 source of truth，损坏可扫描 manifests 重建 |
| 6 | 指纹职责分离 | content_hash=文件身份 / config_fingerprint=配置身份 / structure_hash=chunking 产物 integrity check |
| 7 | AC-2 可测化 | 改为 **canonical serialization 后逐字节一致**（稳定键排序 + canonical JSON + sha256；不用 uuid id） |
| 8 | merge 指纹定义死 | merge_input_fingerprint 基于传给 judge_merges 的**最终 pairs** 的 canonical serializer（非中间对象） |
| 9 | CheckpointStore 职责 | 只提供 put/get_exact/exists/delete/list；**兼容判定归 api 层** |
| 10 | 文件安全 | 目录权限 / novel_id 仅 UUID（防路径穿越）/ 原子写 / 并发锁 / 磁盘写失败降级（不使 job failed，避免浪费 LLM 工作） |

### Review Round 2 修订（2026-08-28，两项阻断修订采纳，合入 Spec v1.2）

| # | 修订 | 内容 |
|---|---|---|
| R1 | COMPLETED 准入收紧 | 存在**可恢复缺口**（FAILED extraction / 本次 judge 失败 / merge judge 缺口）→ manifest 保持 IN_PROGRESS，**即使本次写库成功 + job completed_with_errors**；仅「无缺口 + 最终图写库成功」允许 COMPLETED。**job 终态与 manifest 状态解耦**（job 表达本次执行结果，manifest 表达可恢复性）——保证下次同文件重传继续重试缺口，而非走幂等零 LLM 路径（AC-9） |
| R2 | index 复合键 | index 改为 `content_hash:config_fingerprint → novel_id`：同一 EPUB 不同配置的 checkpoint **并存、互不覆盖、各自可被正确发现**（AC-11）；扫描兜底按双条件匹配 |

## 18. Follow-up

1. Spec Review Round 2 通过（2026-08-28；两项阻断修订合入 v1.2：COMPLETED 准入收紧 R1 / index 复合键 R2）→ 进入实现；
2. ✅ 实现完成（checkpoint 层 / 编排 / ReplayJudge·ReplayMergeJudge / 测试）并提交 `d726d2f`（unit 257 + integration 16 全绿，AC-1..AC-11）；
3. ✅ **真实评估完成（Run 5，qwen3.8-flash，2026-08-28）**：resume 时 extraction 26/27 chunk 零重复、**judge 19/19 全部重放（delta=0）**、novel 复用 + 新 job、resume job completed（failed=[]）；AC-2 逐字节一致性在 mock 层成立，真实 LLM 下因 P06 方差与 Run A 自身失败不可逐字节比较（结构级差异归因记录）。详见 [评估报告](../evaluation/2026-08-28-biancheng-p19-resume-eval.md)；
4. 评估发现（既有行为，另立记录/跟进）：merge_judge 请求体超 DashScope 6MB 上限（桥接证据过大）；qwen3.7-flash 免费额度耗尽（403 FreeTierOnly，账户域）；真实网络不稳定（RemoteProtocolError/ReadTimeout）——resume/重试机制均正确处理；
5. 长期决策登记 DECISIONS.md（D-18，docs-only，独立提交不回改 d726d2f）。
2. 实现（见 Spec §10 文件清单）；
3. unit + integration 测试（Spec §13 测试矩阵）；
4. 真实评估（如适用：真实 LLM 中断恢复验证，按 TESTING.md §6/§9 Environment Baseline）；
5. 评估报告回写本 Record。

## 19. Current Limitation

未实现。设计边界内已知限制：

- resume 必须重传同一 EPUB 文件（不持久化 epub 原件）；
- 旧 job_id 跨进程不可恢复（D-14 保持）；
- P11（全 chunk 失败 → job failed）不在本任务修复，但与 resume 的 failed-block 语义交互；
- 磁盘占用 = checkpoint 文件总量（可用 `CheckpointStore.delete(novel_id)` 清理）。

## 20. Do Not Reopen

- 实现后若「中断重跑仍重复消耗 token」再现，先检查（按序）：
  1. **fingerprint 是否失效**（prompt / model / chunk 配置 / schema_version / chunker/extractor 版本变化 → 旧 checkpoint 被有意作废，属设计行为，不是回归）；
  2. **checkpoint 是否被清理**（delete / 目录丢失 / `er_checkpoint_enabled=False`）；
  3. **code regression**（resume 编排是否被改动 / extractor 钩子是否丢失）；
  4. **输入变化**（重传文件是否与首次不同 → structure_hash 不匹配 → 有意作废）。
- 不要重复「中断只能全量重跑」的旧假设；不要因为「同 chunk 已有 extraction」就盲目复用旧 judge（必须先校验 judge 版本 + input fingerprint）。
- 不要在未解除 D-14 / 未走独立立项的情况下引入持久化 JobStore 来「修复」本问题。
