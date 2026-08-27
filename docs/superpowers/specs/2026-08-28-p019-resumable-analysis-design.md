# P19 Design Spec — Resumable Analysis / Checkpointed LLM Pipeline

- **日期**: 2026-08-28
- **版本**: v1.2（Round 1 十项 + Round 2 两项修订；修订记录见 §0）
- **状态**: Review Round 2 通过（2026-08-28；两项阻断修订已合入 v1.2）→ 进入实现阶段（按 §16 从 Step 1 执行）
- **前置**: [P019 Problem Record](../problems/P019-resumable-analysis.md)（Evidence 已收集、层归属已定）；PROCESS.md §5 准入
- **约束（沿用并锁定）**:
  - 不改 extraction / resolver / merge 语义规则（PIPELINE_LAYER §4 决策矩阵逐字节不变）；
  - 不重开 P16 / P17 / P18 冻结决策（D-6 / D-9 / D-10 / D-13）；
  - 不 supersede D-14（JobStore 保持进程内；**checkpoint 才是 durable recovery state**）；
  - `POST /api/novels` 与前端零改动；API / DTO 向后兼容；
  - 本阶段不新增 resume API、不引入持久化 JobStore。

---

## 0. 修订记录

### v1.2（2026-08-28，Review Round 2 两项阻断修订）

| # | 阻断项 | v1.2 修订 |
|---|---|---|
| R1 | manifest COMPLETED 准入过宽：job completed_with_errors 也可能被标 COMPLETED，导致 FAILED chunk 永不被重试 | COMPLETED 准入收紧：**只要存在可恢复缺口（FAILED extraction / 本次 judge 失败 / merge judge 缺口）→ manifest 保持 IN_PROGRESS**，即使本次 Neo4j 写入成功、job 为 completed_with_errors；只有「无可恢复缺口 + 最终图写库成功」才允许 COMPLETED。**job 终态与 manifest 状态解耦**（job 表达本次执行结果，manifest 表达可恢复性），见 §4.2 / §6.3 / §10.3-10.4 |
| R2 | index `{content_hash: novel_id}` 单值无法支持同一 EPUB 多 config_fingerprint 并存（互相覆盖/lost） | index 改为**复合键** `{content_hash}:{config_fingerprint} -> novel_id`：不同配置的 checkpoint 天然并存、各自可被发现；扫描兜底按双条件匹配；异常多命中取 updated_at 最新 + 日志，见 §4.1 / §7.1 |

### v1.1（2026-08-28，Review Round 1 采纳 10 条修订）

| # | v1 问题 | v1.1 修订 |
|---|---|---|
| 1 | manifest.status 含 FAILED 语义矛盾 | 收紧为 `IN_PROGRESS / COMPLETED` 两态；异常终止保持 IN_PROGRESS（recoverable state）；job 的 FAILED 是 execution state，不进 manifest；损坏 manifest 视为不存在 |
| 2 | FAILED → PERMANENT_FAILED 永久封死与自动续跑矛盾 | **删除 PERMANENT_FAILED / attempts 熔断**：FAILED chunk 每次 resume 均重新尝试；attempts 仅作观测计数；单次 job 失败由既有 FailedBlock → job 终态表达 |
| 3 | 「完整重传返回既有 job」未定义 job_id | 明确：**不复活历史 job**；创建**新的 terminal job**（新 job_id，done_chunks = chunk_count，final_stats 复用，零 LLM） |
| 4 | get_by_novel → create 存在 TOCTOU 竞态 | `JobStore.get_or_create_running_job(novel_id)` 在**单锁临界区**内完成 check + create；作为 AC-8 |
| 5 | index.json 并发写 lost update | index 更新用**进程级锁 + read-modify-write + atomic rename**；index 非 source of truth，损坏/丢失可扫描 manifests 重建 |
| 6 | content_hash / structure_hash 职责不清 | 三指纹职责分离：content_hash = 文件身份；config_fingerprint = 配置身份；structure_hash = chunking 产物 integrity check（见 §5.1） |
| 7 | AC-2「逐字节一致」过强 | 改为 **canonical serialization 后逐字节一致**：稳定键排序 + canonical JSON + sha256 比较（不使用 uuid id，见 §12 AC-2） |
| 8 | merge judge 输入指纹仅文字描述 | 定义 **canonical serializer**：基于传给 `judge_merges()` 的最终 pairs 序列化结果计算（非中间对象，见 §5.4） |
| 9 | CheckpointStore「版本判定」与「不做业务决策」冲突 | CheckpointStore 只提供 `put / get_exact / exists / delete / list`；**兼容性判定归 api 层**（见 §10.1） |
| 10 | chunks.jsonl 全文缺文件安全约束 | 新增 §4.7 文件安全与完整性约束（目录权限 / 路径穿越防护 / 原子写 / 并发锁 / 磁盘写失败降级语义） |

### v1（2026-08-28 初稿）

- 初版设计（checkpoint 数据模型 / 指纹身份 / 自动续跑 / 验收 / 测试矩阵）。v1 的「PERMANENT_FAILED 熔断」「manifest FAILED 态」「AC-2 直接逐字节比较」经 Round 1 评审被修订（见上表），不作为现行语义。

---

## 1. 背景与目标

### 1.1 问题

一次小说分析消耗大量 token（抽取每 chunk 一次 + judge 每 chunk 一次，judge 输入含整块 chunk 正文）。job 中途因 token quota / 网络 / 进程异常失败后，已完成 chunk 无持久化恢复能力；重跑 = 全量重抽 + 重 judge = 重复消耗 token。

### 1.2 目标

把 ingest 改造成**可恢复、幂等、可增量执行**的 pipeline：

1. **checkpoint**：extraction / judge 结果在成功后立即持久化；
2. **resume**：中断后重传同一文件自动续跑，跳过 COMPLETED 阶段，只继续未完成阶段；
3. **extraction result 持久化**：成为 durable 中间产物（未来可支持 resolver/merge 级实验复用，见 §15）；
4. **job recovery**：durable source of truth = checkpoint（job 只是 execution handle）；
5. **token 成本**：恢复时已完成阶段**零重复 LLM 调用**。

### 1.3 恢复目标（明确口径）

> 已完成 checkpoint = 零重复 LLM 调用；只重放真正未完成的阶段。

---

## 2. 现状调用链与持久化位置（代码事实，2026-08-28）

```text
POST /api/novels
 └─ _run_ingest (novels.py, BackgroundTasks)
     ├─ read_epub            → chapters                      [内存]
     ├─ chunk_chapters       → chunks（chunk_id 全局递增）    [内存]
     ├─ extract_all          → ExtractionBundle{results,failed} [内存]
     │    └─ extract_one ×N（ThreadPoolExecutor；429/5xx 重试 1 次；validation 不重试）
     ├─ EntityResolver.resolve ×N（chunk_id 升序；每 chunk 至多一次 batch judge） [内存]
     │    └─ llm_client.judge_aliases(chunk_text, pending)   ← 输入含整块 chunk 正文
     ├─ merge_extractions / apply_aliases / decide_merges（一次 judge_merges）→ apply_merges
     ├─ finalize / drop_unconfirmed_entities
     ├─ db.upsert_novel + db.upsert_graph（Neo4j 单事务；仅最终图）
     └─ job_store.update（进程内；D-14：重启丢失）
```

**LLM 调用点（全部 token 成本）**：`extract_chunk`（每 chunk）、`judge_aliases`（每 chunk 至多一次）、`judge_merges`（末尾一次 batch）。

**现状无任何持久化中间态**：`ExtractionBundle` 纯内存；judge 结果不落盘；JobStore 进程内（D-14）；Neo4j 只存最终图；lineage raw extraction 默认关闭且无恢复语义（不可复用，P019 §11）。

---

## 3. 核心概念与职责分层（钉死）

| 概念 | 职责 | 生命周期 |
|---|---|---|
| **job_id** | 当前执行实例的 execution handle | 进程内（D-14 保持）；失败后保持终态（FAILED/completed_with_errors），**不复活** |
| **novel_id** | 小说身份（D-2：Person 身份 = (novel_id, name)） | durable；可被新的 job 复用 |
| **checkpoint** | **durable recovery state**：已完成的 extraction/judge 阶段 | durable（文件）；本任务的 source of truth |

> **「Job 是 execution handle，Checkpoint 才是 recovery state。」**（P019 §17 Decision 5）
>
> FastAPI 进程重启后旧 job_id 消失也没关系：用户再次上传同一文件，系统通过 `novel_id + content_hash + config_fingerprint + checkpoint` 恢复。

**续跑流程（用户拍板语义）**：
- 首次分析：job A + novel X；中途失败 → A 保持终态；
- 用户重传同一 EPUB → 命中兼容的 novel X + checkpoint → 创建新 job B；
- B 跳过已 checkpoint 阶段，仅继续未完成阶段。

---

## 4. Durable Checkpoint 数据模型

### 4.1 目录布局

```
checkpoints/                                  # 配置 er_checkpoint_dir（默认 "checkpoints"，相对 backend cwd）
  index.json                                  # 复合键 {content_hash}:{config_fingerprint} -> novel_id（加速索引，非 source of truth）
  {novel_id}/
    manifest.json                             # 小说级元数据 + 版本指纹 + 状态
    chunks.jsonl                              # 每 chunk 一行（含全文；resolver 重放需要 chunk.text）
    extraction/{chunk_id}.json                # 每 chunk 一个 extraction checkpoint（COMPLETED / FAILED）
    judge/{chunk_id}/{input_fingerprint}.json # 每 chunk 每 judge 输入一个 judge checkpoint
    merge_judge/{input_fingerprint}.json      # 末尾一次 merge judge checkpoint
```

**index.json 并发写与多配置策略（v1.2）**：
- **复合键**：`{content_hash}:{config_fingerprint} -> novel_id`（v1.2，R2）——同一 EPUB 不同配置（prompt/model/切块等）对应不同 novel_id 的 checkpoint **天然并存、互不覆盖、各自可被正确发现**；
- 更新必须**进程级锁 + read-modify-write + atomic rename**（防多 novel 并发创建/更新时 lost update）；
- index 只是加速索引，**不是 source of truth**；损坏/丢失时允许**扫描 manifests 重建**（`rebuild_index()`，按 content_hash + config_fingerprint 双条件重建成复合键）；
- `find_manifest(content_hash, config_fingerprint)` 命中失败（index 缺失/不一致）→ 回退全量扫描 manifests（结果一致，仅慢）；异常多命中（同 key 多 manifest）→ 取 `updated_at` 最新者 + 日志警告。

### 4.2 manifest.json

```json
{
  "schema_version": 1,
  "novel_id": "uuid",
  "title": "边城",
  "content_hash": "sha256(epub_bytes)",
  "config_fingerprint": "sha256(canonical JSON of §5.2 version tuple)",
  "chunking_version": "1",
  "extractor_version": "1",
  "extraction_prompt_hash": "sha256(...)",
  "judge_prompt_hash": "sha256(...)",
  "merge_prompt_hash": "sha256(...)",
  "model": "qwen3.7-...",
  "chunk_size": 4000,
  "chunk_overlap": 400,
  "structure_hash": "sha256(chunks 结构+全文)",
  "chunk_count": 27,
  "status": "IN_PROGRESS | COMPLETED",
  "created_at": "...",
  "updated_at": "...",
  "final_stats": { }                          // COMPLETED 时写入；幂等重传时复用
}
```

**status 语义（v1.1 收紧 + v1.2 R1 准入）**：
- 仅 `IN_PROGRESS / COMPLETED` 两态；**无 FAILED**；
- 异常终止（进程崩溃 / job failed）→ **manifest 保持 IN_PROGRESS**（recoverable state）；job 的 FAILED 是 execution state，与 checkpoint 状态解耦；
- **COMPLETED 准入（v1.2 R1，全部满足才允许）**：
  1. 最终图写库成功（`db.upsert_graph` 完成）；
  2. **无 FAILED extraction**（全部 extraction checkpoint 均为 COMPLETED）；
  3. **无本次 judge 失败**（ReplayJudge 无 `judge_failed` 记录，见 §10.3）；
  4. **无 merge judge 缺口**（merge judge 成功，或本次无 merge pair 无需判定）。
  任一不满足 → manifest 保持 IN_PROGRESS（**即使本次 job 已 terminal（completed_with_errors）**——下次同文件重传继续重试缺口，而不是走幂等零 LLM 路径）；
- 损坏 / 无法解析的 manifest → **视为不存在**（find_manifest 跳过 + 日志警告；可选 quarantine 重命名为 `{novel_id}.stale`，实现时定）。

### 4.3 chunks.jsonl

每行：`{"chunk_id": 1, "chapter_id": 1, "chapter_title": "...", "start_offset": 0, "end_offset": 3999, "section_type": "BODY", "text": "..."}`

- 恢复时**直接使用持久化的 chunks**（不重新解析 epub），保证 chunk 输入与首次运行逐字节一致；
- 重传文件仅用于身份匹配（content_hash + structure_hash 校验），不参与恢复期解析。

### 4.4 extraction checkpoint —— `extraction/{chunk_id}.json`

```json
{
  "schema_version": 1,
  "chunk_id": 12,
  "status": "COMPLETED",                    // 或 "FAILED"（持久化失败标记）
  "attempts": 1,                            // 累计尝试次数（观测计数；v1.1：不熔断）
  "error": null,                            // FAILED 时的错误信息
  "config_fingerprint": "...",              // 写入时版本（复用时必须匹配当前指纹）
  "result": { "characters": [...], "relationships": [...] }   // ExtractionResult.model_dump()
}
```

- **成功 → 立即写 COMPLETED**（`on_chunk_result` 钩子，见 §10）；
- **失败 → 写 FAILED 标记**（error + attempts+1）；
- **v1.1：attempts 仅观测计数，不熔断**——FAILED chunk 在**每次 resume 都重新尝试**（新 LLM 调用）；单次 job 内的失败由既有 FailedBlock → job `completed_with_errors` 表达（与现状一致）；**无 PERMANENT_FAILED**。

### 4.5 judge checkpoint —— `judge/{chunk_id}/{input_fingerprint}.json`

```json
{
  "schema_version": 1,
  "chunk_id": 12,
  "judge_version": { "judge_prompt_hash": "...", "model": "...", "config_fingerprint": "..." },
  "input_fingerprint": "sha256(canonical JSON of {text, pending})",
  "result": { "resolutions": [...] }        // AliasJudgeResult.model_dump()
}
```

- **judge 成功后立即持久化**（包装器内，见 §10.3）；
- **judge 失败不持久化** → resume 时缺失 → 重新调用 LLM（这正是期望的重试语义：上次失败的 judge 值得重试）；
- **identity 必须包含 input_fingerprint**：同一 chunk 可能因候选集 / resolver 状态变化产生多个 judge 输入（P019 §17 Decision 4）——不同输入 = 不同文件，天然共存，各自独立重放。

### 4.6 merge judge checkpoint —— `merge_judge/{input_fingerprint}.json`

```json
{
  "schema_version": 1,
  "merge_version": { "merge_prompt_hash": "...", "model": "...", "config_fingerprint": "..." },
  "input_fingerprint": "sha256(canonical serialization of 最终 pairs 输入)",
  "result": { "merges": [...] }             // MergeJudgeResult.model_dump()
}
```

### 4.7 文件安全与完整性约束（v1.1 新增）

| 约束 | 要求 |
|---|---|
| 目录权限 | checkpoint 目录创建时设私有权限（如 0700 / 继承 umask）；位于 backend cwd 下、**不经 HTTP 静态服务暴露**（api 不 serve 该路径） |
| 路径穿越防护 | `novel_id` **只接受 UUID 格式**（`uuid.UUID(novel_id)` 校验，失败即拒绝）——杜绝用户输入拼接路径；`chunk_id` 只接受正整数；`input_fingerprint` 只接受 `[0-9a-f]{64}`（sha256 hex） |
| 原子写 | 所有文件写入 = tmp 文件 + `os.replace`（atomic rename），崩溃不产生半文件 |
| 并发安全 | 进程级锁保护 manifest / index / 目录级写（各 chunk 文件天然独立，无需锁） |
| 部分写入 | 读取时 JSON 解析失败 → 视为「该 checkpoint 不存在」（安全降级，不崩溃） |
| 磁盘写失败 | **checkpoint 写失败 → 记日志警告 + 该结果视为未持久化（不中断 LLM 工作、不使 job failed）**——checkpoint 是可靠性增强；写失败降级到「该阶段未 checkpoint」（= 现状语义），**绝不因 checkpoint 故障浪费已完成的 LLM 工作**（违背 P19 核心目标）。job stats 记录 `checkpoint_warnings` 计数（观测） |
| 磁盘空间 | 写失败路径同上（降级 + 日志）；不做主动配额检测（运维职责，记录为已知限制） |

---

## 5. 版本与指纹身份（checkpoint 兼容判定的唯一依据）

### 5.1 三个指纹的职责分工（v1.1 明确，不重叠）

| 指纹 | 职责 | 防什么 |
|---|---|---|
| `content_hash`（sha256 epub bytes） | **上传文件身份** | 不同文件被误认同一 novel |
| `config_fingerprint`（版本元组） | **分析配置身份** | 版本/模型/prompt/切块配置变化时复用旧结果 |
| `structure_hash`（chunks 结构+全文） | **chunking 产物 integrity check** | chunker 实际产物漂移（同一文件 + 同配置下的意外差异） |

- content_hash + config_fingerprint 已能识别身份；structure_hash 是**一致性校验**（防 chunking 实现漂移），不是第三套版本兼容机制；
- 三者任一不匹配 → 视为不同分析（新 novel_id），绝不半复用。

### 5.2 版本常量与配置指纹

| 常量 | 位置 | 含义 | 变更时机 |
|---|---|---|---|
| `CHECKPOINT_SCHEMA_VERSION = 1` | checkpoint 模块 | checkpoint 文件格式版本 | 文件格式不兼容变更时 +1 |
| `CHUNKER_VERSION = "1"` | `chunker.py` | 切块逻辑版本 | chunk 边界逻辑变更时 +1 |
| `EXTRACTOR_VERSION = "1"` | `extractor.py` | 抽取编排逻辑版本 | extract 调用/重试语义变更时 +1 |

`config_fingerprint = sha256(canonical JSON of [schema_version, chunking_version, extractor_version, extraction_prompt_hash, judge_prompt_hash, merge_prompt_hash, model, chunk_size, chunk_overlap])`

- prompt hash 由 api 层从 `llm_client` 的 prompt 常量计算（checkpoint 模块保持零业务依赖）；
- **prompt 必须入指纹**（A-1 教训）：prompt 一变，旧 extraction/judge 语义即失效，旧 checkpoint 必须作废（→ 全新 novel_id 全新分析）。

### 5.3 结构指纹（structure_hash）

`structure_hash = sha256(canonical JSON of chunks[chunk_id, chapter_id, start_offset, end_offset, section_type, text])`

- 重传时重新 `read_epub + chunk_chapters` 计算，与 manifest 比对；
- 不匹配（文件内容不同 / chunker 实际产物漂移）→ 视为不同分析 → 新 novel_id。

### 5.4 输入指纹（canonical serializer，v1.1 定义死）

**judge_input_fingerprint**（resolver 传入的最终入参）：

```python
def judge_input_fingerprint(chunk_text: str, pending: list[PendingMention]) -> str:
    payload = {
        "text": chunk_text,
        "pending": [
            {"mention": p.mention,
             "candidates": [{"canonical": c.canonical, "matched_names": c.matched_names}
                            for c in p.candidates]}
            for p in pending],
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False)).hexdigest()
```

- 基于 **resolver 实际传入 judge 的最终 (chunk_text, pending)** 计算（pending 顺序 = resolver 确定性构造顺序）；
- resolver 确定性 ⇒ 恢复时同 chunk 输入一致 ⇒ 指纹命中 ⇒ 重放；候选集 / resolver 状态变化 ⇒ miss ⇒ 重新调用 LLM（**绝不盲目复用旧 judge**）。

**merge_input_fingerprint**（v1.1：基于传给 `judge_merges()` 的最终 pairs 对象，canonical serialization，非中间对象）：

```python
def merge_input_fingerprint(pairs: list[MergePair]) -> str:
    payload = [
        {"a": {"canonical": p.a.canonical, "aliases": p.a.aliases,
               "first_seen_chunk": p.a.first_seen_chunk, "mention_count": p.a.mention_count,
               "chapters": sorted(p.a.chapters)},
         "b": {"canonical": p.b.canonical, "aliases": p.b.aliases,
               "first_seen_chunk": p.b.first_seen_chunk, "mention_count": p.b.mention_count,
               "chapters": sorted(p.b.chapters)},
         "bridge_evidence": [{"chunk_id": e.chunk_id, "chapter_id": e.chapter_id,
                              "mention": e.mention, "text": e.text}
                             for e in p.bridge_evidence]}
        for p in pairs]
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False)).hexdigest()
```

- 与 `llm_client.judge_merges` 的 wire payload **结构一致**（加 sort_keys 规范化）；字段均为 str/int/list，无 float/None 漂移风险；
- ReplayMergeJudge 在收到 pairs 参数时即时计算（见 §10.3）。

---

## 6. 各阶段 checkpoint 状态机

### 6.1 extraction chunk 状态（v1.1：无熔断）

```
PENDING ──(开始抽取)──▶ RUNNING ──(成功+持久化)──▶ COMPLETED
                          │
                          └──(失败+持久化标记)──▶ FAILED ──(任何后续 resume 重新尝试)──▶ RUNNING ...
```

- COMPLETED 且 config_fingerprint 匹配 → resume 跳过（零调用）；
- FAILED → **每次 resume 重新尝试**（attempts+1 仅计数）；单次 job 失败由 FailedBlock → `completed_with_errors` 表达（与现状一致）；
- **无 PERMANENT_FAILED**（v1.1 删除：transient 故障不得永久封死 checkpoint）。

### 6.2 judge chunk 状态（由文件存在性表达）

```
无文件 ──(judge 调用成功+持久化)──▶ 有文件（可重放）
无文件 ──(judge 调用失败)────────▶ 仍无文件（resume 时重试——期望语义）
```

### 6.3 manifest 状态（v1.1 两态 + v1.2 COMPLETED 准入）

```
IN_PROGRESS ──(COMPLETED 准入全部满足：无 FAILED extraction + 无 judge 失败 + 无 merge 缺口 + 写库成功)──▶ COMPLETED
     │
     └──(异常终止 / job 终态为 completed_with_errors 但存在可恢复缺口)──▶ 保持 IN_PROGRESS
```

- **job 终态 ≠ manifest 状态**：job completed_with_errors（有缺口）→ manifest 仍 IN_PROGRESS；job completed（无缺口）→ manifest COMPLETED；job failed（异常）→ manifest IN_PROGRESS；
- 完整重传的幂等判定依据 **manifest.status == COMPLETED**（§7.1 Step 6）；IN_PROGRESS 一律进入 resume（含重试缺口）。

---

## 7. 同文件自动续跑流程

### 7.1 `POST /api/novels`（签名不变）

```text
1. 校验 epub / 大小（现状不变）
2. content_hash = sha256(data)；fingerprint = compute_config_fingerprint(settings)   # 当前代码版本
3. manifest = CheckpointStore.find_manifest(content_hash, fingerprint)   # v1.2 复合键：content_hash:config_fingerprint
                                                                         # 优先走 index，回退扫描（双条件匹配）
4. if manifest is None → novel_id = uuid4()（全新分析；同文件其它配置的 checkpoint 不受影响，R2 并存语义）
   else:
     re-parse: chapters/chunks ← read_epub+chunk_chapters(data)
     if compute_structure_hash(chunks) != manifest.structure_hash → novel_id = uuid4()（chunking 产物漂移 → 全新分析）
     else → novel_id = manifest.novel_id（复用；resume 或幂等）
5. job 创建（原子防重，见 §8.3）：
   if manifest 命中（novel_id 复用路径）:
     (job_id, created) = job_store.get_or_create_running_job(novel_id, str(uuid4()))
     if not created: return NovelCreateResponse(novel_id, job_id)     # 已有非终态 job → 幂等返回
   else:
     job_id = str(uuid4()); job_store.create(job_id, novel_id)
6. if manifest is not None and manifest.status == COMPLETED（完整完成重传，零缺口）:
     # 不复活历史 job；创建新的 terminal job（同步终态，零 LLM，不启动 background task）
     job_store.update(job_id, status=JobStatus.completed,
                      done_chunks=manifest.chunk_count, total_chunks=manifest.chunk_count,
                      stats=manifest.final_stats)
     return NovelCreateResponse(novel_id, job_id)
   # IN_PROGRESS（含 job 曾 completed_with_errors 但存在可恢复缺口，v1.2 R1）→ 进入 resume（Step 7）
7. background(_run_ingest, ...)；返回 NovelCreateResponse(novel_id, job_id)   # 结构不变
```

### 7.2 `_run_ingest`（resume-aware，阶段顺序不变）

```text
1. cp = CheckpointStore(dir, novel_id)
   cp.load_or_create(manifest)          # 首次建 manifest（IN_PROGRESS）；resume 读既有
2. chunks = chunk_chapters(...)（与首次相同配置）
   cp.save_chunks(chunks)               # 幂等覆盖；恢复期以持久化 chunks 为准
3. 抽取阶段：
   done = cp.completed_extraction_ids()               # COMPLETED 且指纹匹配
   todo = [c for c in chunks if c.chunk_id not in done]
   bundle = extract_all(llm_client, todo, concurrency,
                        on_chunk_done=job_store.increment_done,
                        on_chunk_result=cp.save_extraction)   # 每结果立即持久化（写失败降级，§4.7）
4. results = cp.load_extraction_results(chunks)       # 全部 chunk（持久化 + 新增），按 chunk_id 升序
   failed  = cp.load_failed_chunks() + bundle.failed  # FAILED（resume 时已重试）与本次失败
5. 消歧阶段（resolver 全量重放，judge 走 ReplayJudge）：
   resolver = EntityResolver(judge=ReplayJudge(cp, llm_client).judge_aliases, lineage=lineage)
   for chunk, result in results: resolver.resolve(chunk, result)     # 与现状逐字节一致
6. 合并阶段（merge judge 走 ReplayMergeJudge）：
   merged = merge_extractions(results); apply_aliases(...)
   merge_out = resolver.decide_merges(ReplayMergeJudge(cp, llm_client).judge_merges, threshold)
   apply_merges(merged, merge_map); finalize/drop_unconfirmed（现状不变）
7. 写库 + 终态（现状写库不变；终态按 v1.2 R1 准入，见 §10.4）：
   db.upsert_novel / db.upsert_graph / count_stats
   无缺口（无 FAILED extraction + 无 judge 失败 + 无 merge 缺口）且写库成功 → cp.mark_complete(final_stats)
   否则 manifest 保持 IN_PROGRESS（job 仍按现状终态）
8. except: cp 保持 IN_PROGRESS（可恢复）；job → failed
```

**关键性质**：
- 抽取阶段只处理未完成 chunk；已完成 chunk 零 LLM 调用；
- 消歧阶段**总是从 chunk 1 全量重放**（CPU 级，确定性），judge 调用被 ReplayJudge 拦截（命中→重放；miss→真调）；
- 崩溃发生在任意阶段 → 该阶段已持久化的结果天然可复用，未持久化的重跑（judge 失败不持久化 = 可重试，P019 §15）。

---

## 8. 失败 / 重试 / 幂等语义

### 8.1 各失败点的恢复行为

| 失败点 | 首次运行行为（现状） | resume 行为 |
|---|---|---|
| extraction 429/5xx（重试后仍失败） | FailedBlock → 内存 failed 列表 | FAILED 标记 + attempts+1 → **重新尝试**（新 LLM 调用） |
| extraction validation error | FailedBlock（不重试） | 同上重新尝试（LLM 非确定性下可能成功） |
| judge 调用失败（resolver 异常路径 fail-safe） | 不落盘 | 重放时无 checkpoint → 重新调用（重试语义） |
| merge judge 一次失败 | merge_stats failed_pairs | 无 checkpoint → 重新调用（重试语义） |
| checkpoint 写失败 | — | **降级**：记日志 + 该结果未 checkpoint（§4.7）；job 不失败 |
| 进程崩溃 / 重启 | 全丢（D-14） | 已持久化 extraction/judge 全部重放；未持久化的重跑 |

### 8.2 attempts 语义（v1.1：无熔断）

- `attempts` 为**跨 resume 累计的观测计数**（extraction FAILED 标记内），供诊断（lineage / 日志）使用；
- **不设熔断上限**：FAILED chunk 每次 resume 均重新尝试——transient 故障（网络/quota 恢复）不会被永久封死；
- 单次 job 内的失败语义不变：FailedBlock → job `completed_with_errors`（P11「全 chunk 失败 → failed」为独立 🔍 问题，不在本任务修复）；
- 权衡（P019 §16）：长期未恢复的 quota 场景下跨 resume 的重复尝试成本 = 每次 resume 每 FAILED chunk 1-2 次调用，**远小于全量重跑**，且与「resume 是可靠恢复机制」语义一致。

### 8.3 幂等与并发防重（v1.1 闭合）

- **同文件完整完成重传**：不复活历史 job → 创建**新的 terminal job**（新 job_id；`done_chunks = total_chunks = chunk_count`；`stats = manifest.final_stats`；同步终态；**零 LLM 调用**；不启动 background task）；
- **同文件进行中重传**：复用 novel_id + 新 job B；B 跳过 COMPLETED；
- **同文件并发重传（TOCTOU 闭合）**：`JobStore.get_or_create_running_job(novel_id, candidate_job_id)` 在**单锁临界区**内完成「按 novel_id 查找非终态 job → 命中返回既有 / 未命中创建」；
  - **AC-8**：同进程并发相同内容上传，**最多产生一个非终态 job**；
  - 实现：`models/job.py` 新增方法（models 层 owns job 状态；JobStore 已有 `self._lock`）。

---

## 9. resume 时 skip vs replay 矩阵（显式）

| 阶段 | 条件 | resume 行为 | LLM 调用 |
|---|---|---|---|
| extraction | checkpoint COMPLETED + config_fingerprint 匹配 | **SKIP** | 0 |
| extraction | checkpoint FAILED | **重新尝试**（attempts+1） | 新调用 |
| extraction | 无 checkpoint | 执行 | 新调用 |
| judge | checkpoint 存在 + judge_version 匹配 + input_fingerprint 匹配 | **重放** | 0 |
| judge | 其他（无 / 版本不匹配 / 输入指纹不匹配） | 重新调用 | 新调用 |
| merge judge | checkpoint 存在 + version 匹配 + input_fingerprint 匹配 | **重放** | 0 |
| merge judge | 其他 | 重新调用 | 新调用 |
| resolver 全量（CPU） | 总是 | 从 chunk 1 全量重放（确定性） | — |
| 写库（Neo4j upsert） | 总是 | 重新执行（幂等 upsert） | — |

---

## 10. 注入点与代码改动清单（Review 通过后实施）

### 10.1 新增：`backend/app/checkpoint/`（新层，纯 I/O，无业务决策）

| 文件 | 内容 |
|---|---|
| `__init__.py` | 导出 CheckpointStore |
| `store.py` | `CheckpointStore`（v1.1 职责收紧 + v1.2 复合索引）：**只提供** `put(key, payload)` / `get_exact(key) -> payload`（含记录 version，比较归调用方）/ `exists(key)` / `delete(key)` / `list(prefix)` + `find_manifest(content_hash, config_fingerprint)`（**复合键** index 优先，回退双条件扫描）/ `rebuild_index()` / `load_or_create_manifest` / `mark_complete(final_stats)`（**准入检查归调用方**，本方法只做状态写入）/ `save_extraction` / `save_judge` / `save_merge_judge` 为上层便捷封装（仍不做兼容判定）；原子写（tmp+rename）；进程级锁（manifest/index）；路径防护（novel_id UUID 校验、chunk_id int、fingerprint hex） |
| `CHECKPOINT_LAYER.md` | 层契约：只做 checkpoint I/O 与完整性（原子写 / 路径防护 / 锁）；**不做任何业务决策**——包括「是否兼容」（兼容判定 = api 层职责，CheckpointStore 只按精确键存取） |

依赖方向：`api → checkpoint`；checkpoint 仅依赖 stdlib + pydantic（**不 import pipeline/models/db**；版本指纹由 api 层计算后传入）。

### 10.2 修改：`pipeline/extractor.py`（纯钩子，语义零改动）

```python
EXTRACTOR_VERSION = "1"     # 新增常量

def extract_one(client, chunk, retries=1, on_chunk_result=None):
    ... 现状逻辑 ...
    # 返回前：if on_chunk_result: on_chunk_result(chunk, out)   # out ∈ (ExtractionResult | FailedBlock)

def extract_all(client, chunks, concurrency=4, on_chunk_done=None, on_chunk_result=None):
    ... 现状逻辑 ...（results/failed 排序不变）
    # pool.submit(extract_one, client, c, 1, on_chunk_result)
```

- `on_chunk_result=None`（默认）→ 行为与现状**逐字节一致**（现有 `test_llm_client.py::test_extract_all_sorts_and_counts_and_callback` 回归锚点）；
- 不改变失败分类、重试次数、排序、并发语义。

### 10.3 新增：`api/novels.py` 内两个包装器（编排层，不改 resolver/llm_client）

```python
class ReplayJudge:
    """judge 包装器：命中兼容 checkpoint → 重放；否则调 LLM 并持久化。resolver 接口不变。
    兼容判定（judge_version / input_fingerprint 比对）在此层完成——CheckpointStore 只做精确键存取。
    v1.2 R1：记录本次运行中 judge 失败（judge_failed_chunks），供编排层 mark_complete 准入。"""
    def __init__(self, cp, llm_client, judge_version):
        self._cp, self._llm = cp, llm_client
        self._judge_version = judge_version
        self._current_chunk_id = 0
        self.judge_failed_chunks: set[int] = set()      # 本次运行 judge 调用失败（LLM 异常）的 chunk

    def judge_aliases(self, chunk_text, pending):        # 签名 = llm_client.judge_aliases
        fp = judge_input_fingerprint(chunk_text, pending)          # §5.4 canonical serializer
        hit = cp.get_exact(f"judge/{self._current_chunk_id}/{fp}.json")
        if hit is not None and self._version_matches(hit):
            return AliasJudgeResult.model_validate(hit["result"])
        try:
            result = llm_client.judge_aliases(chunk_text, pending)
        except Exception:
            self.judge_failed_chunks.add(self._current_chunk_id)    # 不持久化 → resume 重试
            raise
        cp.put(f"judge/{self._current_chunk_id}/{fp}.json", {...version, fp, result})   # 成功才持久化
        return result

class ReplayMergeJudge:   # 同理；merge_input_fingerprint = §5.4 canonical serializer(pairs)
    def __init__(self, cp, llm_client, merge_version):
        ...
        self.merge_failed = False                    # v1.2 R1：merge judge 缺口标记
```

> 注意：judge 包装器需要知道「当前 chunk_id」——resolver 是**每 chunk 调用一次 judge**（D-17 B1 并入同批），
> 包装器在每次 `judge_aliases` 调用前由编排层设置 `current_chunk_id`（编排层在 for 循环内同步，不读 resolver 内部状态）。

### 10.4 修改：`api/novels.py`（编排重构）

- `create_novel`：content_hash 计算 + index 查找（回退扫描）+ fingerprint/structure 校验 + novel_id 复用/新建 + `get_or_create_running_job` 原子防重 + COMPLETED 幂等路径（§7.1）；
- `_run_ingest`：按 §7.2 流程接入 CheckpointStore / ReplayJudge / ReplayMergeJudge；prompt hash 与 config_fingerprint 计算函数（读取 `llm_client` prompt 常量 + settings）；
- 终态（v1.2 R1 COMPLETED 准入，编排层判定）：
  ```text
  gaps = [c for c in extraction checkpoints if status != COMPLETED]      # FAILED extraction 缺口
         + replay_judge.judge_failed_chunks                              # 本次 judge 失败缺口
         + ([chunk] if replay_merge.merge_failed else [])                # merge judge 缺口
  if 写库成功 and not gaps:
      cp.mark_complete(final_stats)      # manifest → COMPLETED（幂等重传可零 LLM）
  else:
      manifest 保持 IN_PROGRESS          # job 仍按现状终态（completed_with_errors / failed）
  job 终态更新（completed / completed_with_errors / failed，现状不变）
  ```

### 10.5 修改：`models/job.py`

- 新增 `get_or_create_running_job(novel_id, candidate_job_id) -> (job_id, created: bool)`：**单锁临界区内**遍历查非终态 job → 命中返回既有 / 未命中创建（v1.1，TOCTOU 闭合）；不改状态机规则。

### 10.6 修改：`config.py`

```python
er_checkpoint_dir: str = "checkpoints"      # 相对 backend cwd（与 er_lineage_dir 同约定）
er_checkpoint_enabled: bool = True          # False = 完全回退现状（不写不查 checkpoint）
```

### 10.7 修改：`.gitignore`

- 追加 `checkpoints/`

### 10.8 层边界核对（AGENTS.md §2 / ARCHITECTURE §3）

- pipeline 不 import checkpoint / api（钩子由 api 注入）；
- checkpoint 不 import pipeline/models/db（版本值由 api 传入）；
- db 层零改动（checkpoint 清理是 api 编排动作，不入 db）；
- 不违反 D-3（Neo4j 仍只有 Novel/Person/RELATES_TO）。

---

## 11. API 兼容性与前端

- `POST /api/novels` 请求/响应结构**不变**；唯一可观察变化：同一内容重传返回**既有 novel_id**（幂等/续跑语义，有意行为）+ **新的 terminal job_id**（完整完成重传，不复活历史 job）；
- `GET /api/jobs/{job_id}`、`GET /api/novels/{id}` 等全部不变；resume 后 job 的 `done_chunks` 从已持久化数起步（既有字段语义）；
- **前端零改动**：上传 → 轮询 job → 终态 → getNovel 流程原样可用。

---

## 12. 核心验收标准（P19 验收基准，必须逐条可验证）

> **AC-1（零重复调用）**：恢复任务时，所有 fingerprint 完全一致且状态为 COMPLETED 的 extraction/judge checkpoint **必须零 LLM 调用**；只有不存在兼容 checkpoint 的阶段才能重新调用 LLM。
>
> **AC-2（结果一致，canonical serialization）**：全量运行 vs 中断后恢复运行，在 **canonical serialization 后逐字节一致**：
>
> ```python
> def canonical_graph_json(graph: MergedGraph) -> str:
>     return json.dumps({
>         "persons": sorted(
>             [{"name": p.name, "aliases": p.aliases,          # aliases 保序（resolver 确定性）
>               "mention_count": p.mention_count,
>               "chapters": sorted(p.chapters),
>               "chunk_ids": sorted(p.chunk_ids)}
>              for p in graph.persons.values()],
>             key=lambda d: d["name"]),
>         "relationships": sorted(
>             [{"source": r.source, "target": r.target, "type": r.type.value,
>               "chunk_ids": sorted(r.chunk_ids), "confidences": r.confidences,   # 保序
>               "evidence": sorted(r.evidence, key=lambda e: (e["chunk_id"], e["chapter_id"], e["text"]))}
>              for r in graph.relationships.values()],
>             key=lambda d: (d["source"], d["target"], d["type"])),
>     }, sort_keys=True, ensure_ascii=False)
>
> # 比较：sha256(canonical_graph_json(full_run)) == sha256(canonical_graph_json(resume_run))
> ```
>
> 明确：**不使用 person.id / Neo4j internal id**（uuid4 每次写库不同）；比较的是语义内容。integration 侧对 Neo4j 查询结果按相同稳定键排序后比较。
>
> **AC-3（幂等）**：已完整完成的同文件重传 → **零 LLM 调用**、返回同一 novel_id + **新 terminal job_id**（done_chunks = chunk_count，final_stats 复用），不复活历史 job。
>
> **AC-4（指纹失效）**：prompt / model / chunk 配置 / schema_version / chunker/extractor 版本任一变化 → 旧 checkpoint 不被复用（全新 novel_id 全新分析）。
>
> **AC-5（judge 多输入）**：同一 chunk 两次不同 judge 输入 → 两个独立 checkpoint 文件，各自按 input_fingerprint 正确重放，互不污染。
>
> **AC-6（语义零改动）**：`er_checkpoint_enabled=False` 时行为与现状逐字节一致；现有 228 unit + 15 integration 零回归。
>
> **AC-7（边界）**：D-14 未 supersede（JobStore 仍进程内）；P16/P17/P18 决策文件零改动；API/DTO/前端零改动。
>
> **AC-8（并发防重）**：同进程并发相同内容上传，最多产生一个非终态 job（`get_or_create_running_job` 单锁临界区）。
>
> **AC-9（manifest 两态 + COMPLETED 准入）**：异常终止（进程崩溃 / job failed）后 manifest 保持 IN_PROGRESS（可恢复）；**COMPLETED 仅当「无 FAILED extraction + 无本次 judge 失败 + 无 merge judge 缺口 + 最终图写库成功」时设置**（v1.2 R1）；**job completed_with_errors 且存在缺口 → manifest 仍 IN_PROGRESS**，下次同文件重传继续重试缺口而非走幂等零 LLM 路径；无 FAILED 态。
>
> **AC-10（checkpoint 写失败降级）**：checkpoint 写失败 → 记日志 + 该结果未 checkpoint（该 chunk resume 时重跑）+ job 正常完成（不因 checkpoint 故障浪费 LLM 工作）。
>
> **AC-11（多配置并存，v1.2 R2）**：同一 EPUB 用不同 config（prompt/model/切块等）分析 → 各自独立 novel_id + 独立 checkpoint，**均可被正确发现、互不覆盖、互不干扰**（index 复合键 `content_hash:config_fingerprint`）。

---

## 13. 测试矩阵

### 13.1 unit（全 mock，无网络/Neo4j）

| 文件 | 用例 |
|---|---|
| `tests/unit/test_checkpoint_store.py`（新） | manifest/chunks/extraction/judge/merge_judge round-trip；原子写（模拟崩溃无半文件）；损坏文件 → 视为缺失（安全降级）；novel_id 隔离；`delete(novel_id)` 清理完整；**index 并发更新无 lost update（多线程）**；index 损坏/丢失 → `rebuild_index()` 重建一致；**多配置并存（AC-11）**：同 content_hash 不同 config_fingerprint → 两个 novel_id 均可经 `find_manifest` 正确发现；**路径防护**（非 UUID novel_id / 非法 chunk_id / 非 hex fingerprint → 拒绝）；**写失败降级**（mock os.replace 失败 → 记日志 + 该结果未 checkpoint，不抛异常）；manifest 两态流转（**AC-9**：completed_with_errors + 缺口 → 保持 IN_PROGRESS） |
| `tests/unit/test_resume_pipeline.py`（新） | **AC-1**：mock LLM 计数，第 N chunk 失败 → resume → 断言 < N 的 extraction 与全部已重放 judge 零调用，新增调用仅限 ≥ N；**AC-2**：全量 run vs resume run 的 `canonical_graph_json` 一致（含 aliases/evidence 排序）；**AC-3**：完整重传零调用 + 同一 novel_id + 新 terminal job；**AC-4**：prompt/model/chunk_size 变更 → 全新分析；**AC-5**：同 chunk 两批 pending → 两文件各自重放；**AC-6**：disabled 路径与现状一致；**AC-8**：多线程并发 `get_or_create_running_job` 同 novel → 仅一个非终态 job；**AC-9**：异常终止保持 IN_PROGRESS；**AC-9b（v1.2 R1）**：job completed_with_errors + FAILED extraction 缺口 → manifest 保持 IN_PROGRESS → 重传 resume 重试 FAILED chunk（不走幂等零 LLM）；无缺口 + 写库成功 → COMPLETED；**AC-10**：checkpoint 写失败不影响 job 完成 |
| `tests/unit/test_extractor_hook.py`（新，或并入） | `on_chunk_result=None` 与现状逐字节一致；有钩子时成功/失败均回调且带正确 outcome |
| `tests/unit/test_job_store.py`（增补） | `get_or_create_running_job`：命中非终态返回既有；终态后返回新建；并发安全（多线程） |
| 既有 `test_llm_client.py` 等 | 零改动（回归锚点） |

### 13.2 integration（真实 Neo4j + mock LLM）

| 文件 | 用例 |
|---|---|
| `tests/integration/test_resume_neo4j.py`（新） | 独立 novel_id 自建自清（`db.delete_novel` + `CheckpointStore.delete`）；mock LLM 失败注入：第 N chunk 失败 → resume → 最终图与全量 run 一致（**Neo4j 查询结果按稳定键排序后比较**，不使用 uuid id）；幂等重传不产生重复 Person |

### 13.3 真实评估（后续，按 TESTING.md §6/§9）

- Environment Baseline：commit / model / chunk_size / overlap / concurrency / novel_id / Neo4j 版本；
- 场景：真实 EPUB 中断（注入 kill / quota 模拟）→ 重传续跑 → 对比最终图与日志 LLM 调用数（应仅剩未完成部分）；
- 评估报告独立落盘，回写 P019。

---

## 14. 迁移 / 兼容策略

- **新目录，无存量迁移**：当前无任何 checkpoint 数据；引入后旧数据不受影响；
- **版本不兼容**：任一 fingerprint 字段不匹配 → 视为不同分析（新 novel_id），**绝不半复用**；损坏/未知 schema 文件 → 视为缺失（跳过/忽略，不崩溃）；可选：不兼容 novel 的 checkpoint 目录重命名隔离（`{novel_id}.stale`），实现时定；
- **回退开关**：`er_checkpoint_enabled=False` → 全链路现状行为（不写不查）；
- **清理**：测试与（未来的）删除功能必须同时 `db.delete_novel(novel_id)` + `CheckpointStore.delete(novel_id)`（删除确认走 AGENTS.md §2 规则）；
- **文件安全**：见 §4.7（目录权限 / 路径穿越防护 / 原子写 / 并发锁 / 磁盘写失败降级）；
- **目录安全**：checkpoint 内容 = 小说正文 + 抽取结果（与 Neo4j chapters 同敏感级），无 API key；.gitignore 排除。

---

## 15. 边界与非目标

| 不做 | 原因 |
|---|---|
| 不新增 resume API / 前端入口 | 用户拍板；重传即续跑，API/前端零改动 |
| 不持久化 epub 原件 | resume 依赖重传同一文件（content_hash 匹配）；chunk 全文已持久化 |
| 不引入持久化 JobStore / 不 supersede D-14 | 用户拍板；checkpoint 是 recovery state |
| 不改 extraction/resolver/merge 语义 | P019 约束 1 |
| 不重开 P16/P17/P18 | P019 约束 2（D-6/D-9/D-10/D-13） |
| 不修 P11（全 chunk 失败 → job failed） | 独立 🔍 问题；与 resume 的 failed-block 语义交互但不阻塞（恢复后重试可自愈部分失败） |
| 不引入 PERMANENT_FAILED / 永久熔断 | v1.1 删除（见 §0 / §6.1 / §8.2） |
| 不做 resolver/merge 级 checkpoint 快照 | 不需要：resolver 确定性 + judge 重放已覆盖；减少状态面 |
| 不做跨进程 job 恢复（旧 job_id 可查） | D-14 边界；重传续跑已覆盖用户场景 |
| 不把 checkpoint 当最终结果权威 | Neo4j 仍是最终图唯一权威 |

**附带的增量执行收益（顺带说明，非本阶段目标）**：持久化的 extraction 结果未来可支持「resolver/merge 语义实验不重抽」（如 P017 D5 系列只改 resolver 时复用 extraction cache）——但必须遵守指纹纪律（resolver 改动不影响 extraction 指纹，可复用；prompt 改动则作废）。

---

## 16. 实施顺序（Review Round 2 通过后执行；本 Spec 不实现）

```text
Step 1  checkpoint 层 + 单元测试（store round-trip / 原子写 / 隔离 / 清理 / 损坏降级 / 路径防护 / index 并发与重建 / 写失败降级 / manifest 两态）
Step 2  extractor 钩子（on_chunk_result）+ 回归锚点测试
Step 3  config 设置 + models.get_or_create_running_job（含并发测试）
Step 4  novels.py 编排重构（create_novel 指纹查找 + 幂等 terminal job + _run_ingest resume 流程 + ReplayJudge/ReplayMergeJudge）
Step 5  unit 测试矩阵（AC-1..AC-10）
Step 6  integration（test_resume_neo4j.py）
Step 7  全量回归（unit 228 + 新增 + integration 15）
Step 8  真实评估（可选，按 TESTING.md）
Step 9  评估报告回写 P019；如产生长期决策（如 checkpoint 层契约）登记 DECISIONS.md
```

每个 Step 独立 commit（一个问题一个 commit，PROCESS.md §3）。

---

## 17. Review Round 2 检查清单（实现前必须逐项确认）

- [ ] **checkpoint identity**：extraction = `chunk_id + config_fingerprint`；judge = `chunk_id + judge_version + judge_input_fingerprint`（canonical serializer 定义死，§5.4）；merge = version + merge_input_fingerprint（最终 pairs 序列化）；
- [ ] **幂等语义**：完整重传 → 新 terminal job（§7.1/§8.3，AC-3）；并发重传 → `get_or_create_running_job` 单锁（AC-8）；FAILED 重试无熔断；
- [ ] **COMPLETED 准入（v1.2 R1）**：无 FAILED extraction + 无本次 judge 失败 + 无 merge 缺口 + 写库成功才允许 COMPLETED；job completed_with_errors + 缺口 → manifest 保持 IN_PROGRESS（AC-9）；
- [ ] **版本兼容**：三指纹职责分离（§5.1）；config_fingerprint 字段集完整；prompt 变更必须作废（§5.2）；structure_hash 为 integrity check；
- [ ] **失败恢复边界**：judge 失败不持久化 = 可重试（§8.1）；崩溃于任意阶段均可恢复（§7.2）；manifest 两态（AC-9）；checkpoint 写失败降级（AC-10）；
- [ ] **语义零改动**：`er_checkpoint_enabled=False` 逐字节一致；P16/P17/P18/D-14/API/前端零改动（AC-6/AC-7）；
- [ ] **并发与文件安全**：index 进程级锁 + read-modify-write + atomic rename（§4.1）；**复合键 `content_hash:config_fingerprint`（AC-11，v1.2 R2）**；novel_id UUID 校验防路径穿越（§4.7）；
- [ ] **AC-2 可测性**：canonical serialization 稳定键定义无遗漏（aliases/evidence 保序、persons/relationships 排序、不用 uuid id）；
- [ ] **层边界**：CheckpointStore 无兼容判定（只 get_exact/put/exists/delete/list）；兼容判定归 api 层（§10.1/§10.3）；
- [ ] **Do Not Reopen 检查**（P019 §20）：无同类记录冲突；无旧方案被证伪；不重复旧修复；不引入持久化 JobStore。

---

## 附录：与现有文档的关系

| 文档 | 关系 |
|---|---|
| [P019 Problem Record](../problems/P019-resumable-analysis.md) | 本 Spec 的 Evidence / 归因 / Decision 依据（§17 含 Review Round 1 修订记录） |
| `PROCESS.md` §5 | 本 Spec 满足「Problem Record + Spec + Review」准入 |
| `DECISIONS.md` D-14 | 保持（本 Spec 不 supersede）；实现后若新增层契约决策再登记 |
| `ARCHITECTURE.md` | 新增 `checkpoint/` 层需在实现时同步更新架构图与依赖方向（api → checkpoint） |
| `PIPELINE_LAYER.md` | 语义决策矩阵零改动；仅 extractor 增加可选钩子（编排层关注点） |
| `TESTING.md` | 真实评估按 §6/§9；回归清单 §8 不动 |
