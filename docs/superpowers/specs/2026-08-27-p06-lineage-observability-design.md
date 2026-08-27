# Task A：P06 Lineage / Observability 最小设计 — ER 全链路可归层观测

- **日期**: 2026-08-27
- **版本**: v2（已评审通过，含 4 项评审修订；实现于 commit 见 git log）
- **状态**: ✅ **已实现**（V0.2.7：`pipeline/lineage.py` + resolver/extractor/merger/novels 旁路打点 + `tools/diagnose_lineage.py`；unit 207+17 / integration 15 全绿）
- **背景**: V0.2.6 验收暴露 P06 链路不可观测——`翠翠的祖父` 未建立、`岳云二老` 未吸收等失败**无法归层**（extraction 未提取？recall 无候选？judge null？admission reject？merge 丢失？），导致结论只能写「无法区分，记 P06/observability 缺口」。
- **前置**: V0.2.6 验收报告 `docs/evaluation/2026-08-27-biancheng-v026-eval.md`；P018 Do Not Reopen「不要因翠翠的祖父 修改 P16-b gate，先上 Task A 观测」。

## 0. 评审修订（v1 → v2，2026-08-27 通过）

实施前补入 4 项工程约束，**均已在本实现落地**：

1. **lineage_id（强制）**：所有 mention lineage 事件携带稳定 `lineage_id`。不同 pipeline 层
   （extraction / recall / judge / admission / registration）的事件通过 `lineage_id` 显式 join，
   **不依赖 (chunk_id, mention) 隐式关联**（同 chunk 同 mention 多次出现时 (chunk_id, mention)
   有歧义）。实现：recorder 每 (mention, chunk 处理实例) 生成一次 uuid，全层事件共享。
2. **extraction_raw 不作为默认 lineage 数据**：`ER_LINEAGE_RAW_EXTRACTION=0` **默认关闭**（v1 §5.2
   曾写「默认开」→ 修订为关）；原始 extraction 三元组是可选 debug 能力，深挖 extraction 时显式开启。
   `ER_LINEAGE=1` 默认只记录最小 mention lineage。
3. **最小离线诊断能力（新增交付物）**：`backend/tools/diagnose_lineage.py` 只读 JSONL（不参与运行时
   业务逻辑），按固定决策序 extraction → category → recall → judge → admission → registration → merge
   输出每个目标 mention 的**唯一故障层 + 决定性证据**。验收不得只验证 JSONL 存在，必须能对
   翠翠的祖父 / 岳云二老 / 弟弟 / 爷爷 逐项归层。
4. **Task A 严守不变量**：不修改任何判定结果 / 不增加 LLM 调用 / 不修改 prompt / 不修改 schema /
   不修改 P16-b / P17；`ER_LINEAGE` 默认关闭时现有 207 + 15 regression 逐字节不变（已实测 224+15 全绿）。
   实现 PR 为**纯 observability change**：若打点被迫修改业务分支则停止报告，不顺手重构 resolver。

## 1. 目标（可验证的完成标准）

下一次真实 ingest 结束后，对任意 mention（如 翠翠的祖父），能**从落盘日志确定性地回答**：

```text
1. mention 是否被 extraction 提取（在 extraction 输出 characters/relationships 中出现？）
2. extraction category 是什么（LLM 标注的 MentionCategory，或 None）
3. 是否进入 role/alias candidate recall（bare/qualified 判定、anchor/headword）
4. judge 是否被调用（是否进 pending 批次）
5. judge 输入候选是什么（candidates 列表，canonical + matched_names）
6. judge 输出是什么（resolves_to = C / null / missing）
7. 最终 admission 是 accept / reject / null / skipped（含 reject 的具体原因）
8. 是否发生后续 merge 丢失（registered canonical 是否被 merge_map 吸收/删除）
```

**验收定义**：对 V0.2.6 中无法归层的 4 个观察项（翠翠的祖父、岳云二老、弟弟、爷爷），用新日志**逐项归层**，每项落在且仅落在一个故障层（或明确「多层并存」），并能给出该层的证据链。

## 2. 设计原则

1. **零业务语义变更**：resolver / hygiene / judge / merge bridge 的判定逻辑、输入、输出**一律不变**；观测是旁路（tap），不是拦截。
2. **零额外 LLM 调用**：只记录已发生的调用与结果。
3. **默认关闭、按需开启**：env 开关 `ER_LINEAGE=1`（默认 off）；关闭时零内存、零 IO 开销。
4. **确定性落盘**：每 novel 一个 lineage 文件（JSONL），job 终态 flush；失败 job 也落盘（except 分支同样 flush）。
5. **最小字段**：只记「决定路径的字段」，不复制 chunk 全文（chunk 文本可通过 chunk_id 回查 EPUB/chunk 缓存，不重复存储）。
6. **不引入 classifier / 不扩展词表 / 不动 schema**：本任务与 P017 D5（Task B）严格分离。

## 3. 需要记录的字段

### 3.1 `LineageEvent`（JSONL 一条 = 一个 mention 的一次处理事件）

```jsonc
{
  "event": "mention_enter | recall | judge | admission | registration",  // v2：一层一条事件
  "lineage_id": "d9ba92deec204240b263f2a622857595",  // v2（评审修订①）：同一次 mention 处理实例
                                                     // 全层共享；join 键，不依赖 (chunk_id, mention)
  "novel_id": "3a54e06a-...",
  "job_id": "d002fdec-...",
  "chunk_id": 11,
  "chapter_id": 10,
  "section_type": "body",

  // ① extraction 层（mention_enter 事件）
  "mention": "翠翠的祖父",
  "extracted": true,                    // 是否出现在本 chunk extraction 输出的 characters/relationships
  "extraction_category": "descriptive", // LLM 标注 category（或 null）
  "hygiene_category": "descriptive",    // hygiene.classify_mention 兜底结果（RC3 强制等）
  "extraction_roles": ["character"],    // character / relationship_source / relationship_target

  // ② recall / role 判定层（recall 事件）
  "role_kind": "qualified",             // bare / qualified / none（classify_role_mention）
  "role_anchor": "翠翠",                 // anchor（X，若 known）
  "role_anchor_known": true,            // X 是否 ∈ known
  "role_headword": "祖父",              // 核词 Y
  "recall_candidates": ["祖父", "翠翠"], // judge 输入候选 canonical（_recall 输出，含 strong/weak）
  "recall_source": "strong_extraction", // known_hit / strong_extraction / strong_text / weak / none

  // ③ judge 层（judge 事件；先记原始判定输出，再走约束校验）
  "judge_called": true,                 // 是否进 pending 批次并调用 judge
  "judge_input_mentions_count": 3,      // 本 chunk judge 批次 mention 数（上下文）
  "judge_input_candidates": ["祖父"],   // 该 mention 的 judge 输入候选（显式记录）
  "judge_resolves_to": "祖父",          // judge 输出（null / missing / canonical）
  "judge_missing": false,               // pending 但 judge 结果中无此 mention（防御路径）
  "judge_error": null,                  // judge 异常类型（exception 路径）

  // ④ admission 层（admission 事件；P16-b / P17 / 既有路径）
  "admission": "accept",                // accept / reject / observation / confirmed / blocked /
                                        // null_registered / null_unresolved / skipped_generic /
                                        // skipped_hardfilter / nonbody_dropped / deferred /
                                        // deferred_unresolved / known_hit / invalid_judge_output /
                                        // exception_registered / exception_unresolved
  "admission_reason": "",               // reject 具体原因：
                                        //   target_mismatch / anchor_mismatch / evidence_lt_2 /
                                        //   cross_canonical_conflict / blocked / judge_null
  "evidence_count": 2,                  // 该 (mention, target) 累计独立 chunk 证据数（P16-b）
  "role_confirmed": true,               // (mention, target) ∈ _role_confirmed
  "role_blocked": false,                // mention ∈ _role_blocked

  // ⑤ 注册/alias 层（registration 事件）
  "registered": true,                   // 是否成为 canonical（或 alias 写入 known）
  "alias_to": "祖父",                    // 若为 alias，写入的 canonical
  "final_canonical": "祖父",            // 本 chunk 处理后的 canonical（known[mention]）
  "provisional": false,                 // 非正文 provisional 注册（-a 语义）

  // ⑥ merge 层（merge_drop 事件，canonical 级；非 mention 级）
  "canonical": "二老",                  // 被吸收 canonical（C_drop）
  "merge_keep": "傩送"                   // 吸收后的 keep canonical
}
```

> 说明：**不记录** chunk 全文 / extraction 原始全文 / judge prompt 全文——chunk_id + mention 即可回查。judge 输入只记 candidates canonical 列表（不含 matched_names 全量，避免膨胀；需要时用 `_index` 快照补查——可另加一个 canonical→matched_names 快照事件）。

### 3.2 辅助事件（非 mention 级）

- `chunk_start`：chunk_id / chapter_id / section_type / text_len（用于核对 chunk 对齐）。
- `canonical_snapshot`（job 末，可选）：全部 canonical → {aliases, mc, chapters}，用于 merge 后核对「图里最终状态」。
- `judge_batch`（可选）：本 chunk judge 批次全体 mention 列表 + 全体 resolutions（用于复现同批次上下文）。

## 4. 放在哪些 pipeline 节点

| # | 节点 | 文件 | 记录点 | 产出 |
|---|---|---|---|---|
| 1 | extraction 输出 | `pipeline/extractor.py`（`extract_all` 内，成功分支） | 每个成功 chunk 的 `ExtractionResult` 全量（characters + category + relationships）dump 为 `extraction_raw` 事件 | 回答「是否被提取 / category 是什么」 |
| 2 | mention 进入 resolver | `pipeline/resolver.py` `resolve()` 的 characters/relationships 循环入口 | 每个 mention 一条事件骨架（mention / extracted / extraction_category / roles） | ① 层证据 |
| 3 | `_resolve_name` 内部分支 | `resolver.py` | known_hit / recall 分支 / 无候选注册 / deferred：记录 recall_candidates、recall_source、hygiene_category、admission 预判 | ② 层证据 |
| 4 | `_apply_judge` | `resolver.py` | judge_called / judge_resolves_to / judge_missing；`_role_alias_decision` 返回后记录 admission / admission_reason / evidence_count / confirmed / blocked | ③④ 层证据 |
| 5 | `_register` / `_add_alias` / `finalize` | `resolver.py` | registered / alias_to / final_canonical；provisional drop | ⑤ 层证据 |
| 6 | merge 决策 | `resolver.py` `decide_merges` | merge_candidate_pairs / merged / failed（已有 stats）；merge_map 落盘 | ⑥ 层证据 |
| 7 | merge 应用 | `pipeline/merger.py` `apply_merges` / `drop_unconfirmed_entities` | merge_dropped / merge_keep（canonical 级） | ⑥ 层证据 |
| 8 | job 终态 flush | `api/novels.py` `_run_ingest`（含 except 分支） | 全部事件写 `ER_LINEAGE_DIR/<novel_id>.jsonl` | 落盘 |

## 5. 如何保证低开销

1. **默认关闭**：`ER_LINEAGE` 未设置时，recorder 为 no-op 实现（所有方法空返回），**零分配、零 IO**；生产路径无感知。
2. **开启时**：
   - 事件先追加内存 list（O(mention 数)）；job 终态一次性写文件（单次 flush），不逐条 IO。
   - 事件只含标量 + 短字符串（candidates 列表 ≤ RECALL_TOP_K=5），单事件 < 500B；27-chunk《边城》约 500-1500 事件 → 文件 < 1MB。
   - 不复制 chunk 文本 / extraction 全文（extraction_raw 是唯一「重」数据，**默认关闭**：
     `ER_LINEAGE_RAW_EXTRACTION=0`；需要深挖 extraction 时显式开启，仅 characters/category/
     relationships 三元组，无原文）。
   - 观测代码**不进入任何判定分支**：全部在分支出口旁路打点（先判定、后记录），无分支改写风险。
3. **测试**：新增 unit 仅验证「recorder 收集字段正确、no-op 零行为、diagnose 归层」；**不**用 lineage
   影响现有 207+15 回归（默认关闭时判定路径逐字节不变）。已实测 unit 224（207+17）/ integration 15 全绿。

## 6. 一次「翠翠的祖父」失败后如何根据日志确定故障层

以 V0.2.6 观察项为例（预期使用新日志后）：

```text
grep '"mention": "翠翠的祖父"' <novel_id>.jsonl
```

| 观察到的日志事实 | 归层 | 结论 / 后续 |
|---|---|---|
| `extracted: false` | **extraction 层** | LLM 未提取该 mention（输出只含 祖父/翠翠）→ 看 extraction_raw 核对；属 P06 提取方差，与 P16-b gate 无关 |
| `extracted: true, extraction_category: null/person` | **D5 / extraction category 层** | category 未标 DESCRIPTIVE → 绕过 gate（爸爸 同型）→ 记 Task B（P017 D5） |
| `extraction_category: descriptive, recall_candidates: []` | **recall 层（P08）** | 无候选 → 走 deferred → 重召回仍无 → unresolved；查 `_recall` 的 known 状态与 RECALL_TOP_K |
| `judge_called: true, judge_resolves_to: null` | **judge 层（P06）** | 候选存在但 judge 判 null → P06 判定方差；可重放 judge_batch 复现 |
| `judge_resolves_to: "祖父", admission: "reject", admission_reason: "target_mismatch"` | **admission 层（gate 行为）** | gate 拒绝（核词/对齐不符）→ 核对 `classify_role_mention` 的 headword 与 canonical 名（如 岳云二老→傩送 的 canonical 名漂移）→ 归 P08 命名或设计 trade-off |
| `judge_resolves_to: "祖父", admission: "reject", admission_reason: "anchor_mismatch"` | **admission 层** | anchor 未在 chunk 文本/候选 → 核对 `_anchor_in_text` 与 chunk 原文 |
| `admission: "accept", registered: true, alias_to: "祖父"` 但图里无 祖父.aliases | **merge/写库层** | 追 merge_dropped / merge_map / upsert 事务；可能 merge 误吸或写库丢失 |
| 事件文件无此 mention 任何记录 | **链路断点** | 事件未记录（bug）或该 chunk 失败（对照 failed_blocks） |

**判定顺序固定为 extraction → category → recall → judge → admission → registration → merge**，任一层的决定性事实出现即可归层；不满足时沿链下探。

## 7. 范围与不变量

- **不改**：resolver 判定、hygiene、prompt、judge 契约、merge bridge、schema、P16-b gate、P17、P16-a、并发/timeout。
- **新增文件**：
  - `pipeline/lineage.py`（recorder：LineageRecorder + create_lineage_recorder，lineage_id 全层关联）
  - `tools/diagnose_lineage.py`（离线归层工具，只读 JSONL，不参与运行时业务逻辑；评审修订③）
  - resolver/extractor/merger/novels 内的旁路打点；env 开关 `ER_LINEAGE` / `ER_LINEAGE_DIR` /
    `ER_LINEAGE_RAW_EXTRACTION`（三者默认 off / lineage / off；评审修订②）
- **测试**：`tests/unit/test_lineage.py`（recorder 字段 + no-op + 判定等价 + diagnose 四案例归层）；
  真实评估时开启 `ER_LINEAGE=1`（建议同时 `ER_LINEAGE_RAW_EXTRACTION=1` 以完全区分「未提取」与
  「链路断点」）跑一次《边城》验证归层能力（验收 = §1 的 4 项观察项全部可归层）。
- **与 Task B 的关系**：Task A 是 Task B 的前置（D5 缺口量化需要 lineage 的 extraction_category 事实）；
  两者独立立项、独立评审。Task B 在 Task A 真实验证完成前不写代码。

## 8. 验收（Done 定义）

1. `ER_LINEAGE=1` 跑《边城》真实 ingest，产物 `<novel_id>.jsonl` 存在且含 §3 全字段（mention 事件均带 lineage_id）。
2. 对 翠翠的祖父 / 岳云二老 / 弟弟 / 爷爷 四项，`tools/diagnose_lineage.py` 给出确定性的归层结论
   （每项一层或明确多层并存 + 证据链；评审修订③：不能只验证 JSONL 存在）。
3. `ER_LINEAGE` 未设置时，unit 全量（207）+ integration（15）**逐字节不变**（判定路径零改动）；已实测 224+15 全绿。
4. 无新增 LLM 调用；文件大小 < 5MB（27-chunk 规模）。
5. 不修改任何业务判定文件的行为（git diff 中判定逻辑文件仅新增旁路打点，无逻辑改动）。
