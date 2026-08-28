# P021 — 《边城》正向合并：`老二` 未并入 `傩送` aliases（deepseek-v4-flash-0731 稳定失败）

- **Status**: ✅ **收敛（产品决策 D-19，2026-08-28）**——Task A 归因完成（`EXTRACTION_LAYER` / D5-a 形态）；产品验收边界：**单次低显著性 mention 不要求稳定覆盖** → 接受该边界，**不修复**；A1 的 `老二` 项正式降为 checkset v2 观察项（A7，OBSERVATION 不判败）；不实施模型探针 / structural alias recall / 任何 pipeline 修改；完整证据链保留于本记录
- **Severity**: High（正向合并基线检查稳定失败 → P20 基线 `INVALID_NOT_REGRESSION_SAFE`，阻塞回归比较）
- **Domain**: ER 算法 / extraction-recall（P08 域）
- **Tags**: alias-merge, recall, extraction-coverage, stable-failure, baseline-exposed
- **First Seen**: 2026-08-28（P20 Step 6 首份真实基线，deepseek-v4-flash-0731，并发 4）
- **Last Verified**: 2026-08-28（3 run 全部复现，stable failure）
- **Evidence Level**: HIGH（3 次独立真实运行确定性重复 + 图结构一致）
- **Decision Type**: FACT（稳定失败观测）+ HYPOTHESIS（归因假设：extraction coverage 缺失 vs judge 判 null，未定）
- **Related Problems**: P08（合并/召回质量域）/ P20（baseline 暴露源）/ P017 D5-a（extraction mention coverage 缺失形态）/ D-11（Task A 先于 Task B）/ P06（judge 方差，待排除）
- **Related Commits**: 无修复；观测源为 P20 baseline commit `d4c30cf`
- **Related Evaluation Reports**: [P20 首份基线报告](../evaluation/2026-08-28-biancheng-quality-baseline.md) + [基线 artifact](../evaluation/baselines/biancheng-2026-08-28-deepseek-v4-flash-0731.json)

## 1. Context

TESTING.md §4 正向 1 组：`傩送 / 二老（+老二）` 期望归并为同一 canonical，aliases 含其余名。P20 Step 6 首份 3-run 真实基线（deepseek-v4-flash-0731）中，检查 A1（single_canonical_with_aliases：members=傩送/二老/老二，alias_contains=二老/老二）**3 次全部 FAIL**，reason 恒为 `aliases 缺失: ['老二']`。

## 2. Symptom

- A1 `FAIL × 3` → 按 P20 v1.1 稳定性分类 = **stable failure**（决定性结果全同且违反期望）；
- 由此 P20 基线 `baseline_status = INVALID_NOT_REGRESSION_SAFE`（v1.1 有效性机制如实触发，禁止用该基线做正常回归比较）。

## 3. Impact

- P20 基线在 A1 修复前无法提供回归比较能力；
- 正向合并（傩送/二老/老二 一族）存在确定性质量缺口：`老二` 这一别名在整个 pipeline 中丢失。

## 4. Trigger

- 真实评估（deepseek-v4-flash-0731）每次运行均复现；与 P20 baseline 的 1-run 验证（`f4c78364`）同模型同行为（1-run 中 A1 同样 FAIL：`aliases 缺失: ['老二']`）。

## 5. Timeline

- **T1（2026-08-28）**：1-run 验证 novel `f4c78364`：A1 FAIL（老二 缺失）；
- **T2（2026-08-28）**：3-run 官方基线 novel `070c03ce` / `40d057fb` / `681538d9`：A1 全 FAIL → **stable failure 定性** → 基线 INVALID → 立项 P021。

## 6. Initial Hypothesis

`老二` 未能成为 `傩送` 的 alias，候选解释（按归因链，PIPELINE_LAYER §4）：

- **(a) extraction coverage 缺失（D5-a 形态）**：`老二` 未被 LLM 提取为 mention → 根本未进入 pipeline；—— **✅ 已证实（Task A）**
- **(b) judge 判 null / 判不同（P06）**：`老二` 被提取，但 judge 未将其 resolves_to 傩送；—— ❌ 排除（无任何 mention 事件）
- **(c) recall 未召回（P08）**：`老二` 出现 chunk 与 傩送 无共现且无桥接，未产生候选（零共享字场景）；—— ❌ 排除（mention 未进入 recall 层）

## 7. Investigation Path

```text
Step 1  lineage 观测重跑（ER_LINEAGE=1，1 run）：确认 老二 mention 是否进入 extraction 输出   ✅ 未进入
Step 2  (a) 若未提取 → extraction coverage（D5-a 形态，P017 域）→ prompt/模型域              ✅ EXTRACTION_LAYER
Step 3  (b) 若已提取 → 查 recall 事件（是否进入候选集）→ judge 事件（resolves_to / null）归层  —（无 mention 事件，跳过）
Step 4  原文定位：老二 在《边城》中出现章节（evidence dump / 确定性文本检索）→ 与该 canonical chapters 对照  ✅ 全文 1 次（chunk15/ch13）
```

## 8. Experiments

- **Task A lineage 归因 run（2026-08-28）**：`ER_LINEAGE=1 + ER_LINEAGE_RAW_EXTRACTION=1`，deepseek-v4-flash-0731，并发 4，fresh novel `764795aa-34b1-4a10-8333-61901bfec1fc`，job=completed（0 failed chunk）；lineage JSONL 落 `.tmp/lineage-p021/764795aa….jsonl`（664 KB）；
- 归层：`tools/diagnose_lineage.py … --mention 老二 --expect 老二=傩送` → **verdict=EXTRACTION_LAYER**；
- 交叉验证：JSONL 全文 `老二` 出现 **0 次**（含 raw extraction）；对照 `二老` 链路正常（judge resolves_to=傩送）→ merge 机制完好。

## 9. Evidence

- **baseline artifact**（`biancheng-2026-08-28-deepseek-v4-flash-0731.json`）：`per_check.A1 = {"classification": "stable", "satisfies_expected": false, "outcome_distribution": {"FAIL": 3}}`；`baseline_status = INVALID_NOT_REGRESSION_SAFE`；`stable_failures = [A1]`；
- **3 个 run 的 result.json**：A1 reason 恒为 `aliases 缺失: ['老二']`；
- **图结构证据（Neo4j 直查，2026-08-28）**：3 个 run 中 傩送 均为**单一 canonical**（mc=15，chapters=[5,6,7,8,12,13,15,17,18,19,20,21,22,24]，三 run 一致），`二老` ∈ aliases，`老二` ∉ aliases——**排除分裂**（非 P08 零共享字分裂）；问题形态 = 老二 这一别名丢失；
- **1-run 佐证**（novel `f4c78364`，同模型）：A1 同 FAIL——行为跨 4 次运行一致；
- **Task A lineage 决定性证据（2026-08-28，novel `764795aa`，ER_LINEAGE=1 + RAW=1）**：
  - `diagnose_lineage.py --mention 老二 --expect 老二=傩送` → **verdict = EXTRACTION_LAYER**（无任何 lineage 事件，raw extraction 亦无）；
  - **lineage JSONL 全文 `老二` 出现 0 次**（含 extraction_raw / chunk_start / judge_batch）；
  - 原文对照（确定性重切）：`老二` 全文**仅出现 1 次**——chunk15/ch13「有人羡慕二老得到碾坊，也有人羡慕碾坊得到**老二**！」（祖父俏皮话，老二=二老=傩送）；该 chunk 的 extraction_raw **提取了 27 个角色（含 傩送/二老）但未提取 老二**；
  - 对照 `二老`：extraction ✓ → recall 候选 ✓ → judge resolves_to=傩送 ✓ ——**merge/recall/judge 机制完好**，问题纯在 extraction 层。

## 10. Root Cause

**`EXTRACTION_LAYER`（extraction mention coverage 缺失，D5-a 形态，P017 域）**：

`老二` 全文仅出现 1 次（chunk15/ch13 祖父俏皮话「有人羡慕二老得到碾坊，也有人羡慕碾坊得到老二！」），deepseek-v4-flash-0731 在该 chunk 提取了 27 个角色（含 傩送/二老）但**未提取 `老二`** → mention 从未进入 pipeline（recall/judge/registration 无事件）→ `老二` 不可能成为 傩送 的 alias → A1 稳定失败。

**与 P017 D5-a 同域**：D5-a = extraction mention coverage 缺失（爸爸/妈妈/大儿子/翠翠的祖父 等未提取）；`老二` 是同一模式的又一实例。P017 D5-a prompt A/B（`cd52844`）已证：prompt 增强对单次低显著性 mention 的覆盖增益有限 + 伴随 descriptive 化风险 → B 未采纳，coverage 缺失归模型域（P06 提取方差）。

## 11. Ruled-out Causes

- ~~canonical 分裂（P08 零共享字分裂）~~：图结构显示单一 canonical（mc=15，三 run 一致），非分裂。
- ~~A1 checkset 定义错误~~：expectation 与 TESTING.md §4 正向 1 组一致（老二 是既有验证成员）；1-run 与 3-run 行为一致。
- ~~recall 未召回（P08）~~：`老二` 无任何 lineage 事件（含 mention_enter）——未到 recall 层，排除。
- ~~judge 判 null（P06）~~：`老二` 无任何 judge 事件——未到 judge 层，排除；对照 `二老` judge 链路正常。

## 12. Failed Approaches

- 无（新立项，归因前无修复方案）。

## 13. Correct Approach

**产品决策（D-19，2026-08-28）：接受该边界，不实施修复。**

- **不实施**：qwen3.8-max 模型探针、deterministic structural alias recall、extraction prompt 修改、recall/judge/P16-b 任何改动；
- **正式验收标准调整**（非"把 FAIL 改成 PASS"）：checkset_version `1 → 2`（CHECKSET_V2）——A1 收敛为核心 gate（傩送/二老 归并），`老二` 移入 **A7 观察检查**（`observation_if_person`，OBSERVATION 不判败、不参与 baseline validity）；TESTING.md §4 正向 1 组同步；
- 依据：P017 D5-a prompt A/B（`cd52844`）——prompt 增强对单次低显著性 mention 覆盖增益有限 + descriptive 化风险；图中单个反说昵称别名的收益不抵修复成本/风险；
- 若未来换更强模型或 extraction 策略：A7 观察趋势转好时，可评估将 老二 升级回核心 gate（**需显式决策 + checkset bump**，禁止静默）。

## 14. Invariants

- 不把 老二 加入 generic 词表或任何词表 hack（D-7）；
- 不引入 classifier 绕过 D5（D-10）；
- 不修改 P16/P17/P18 冻结语义（D-6/D-9）；
- P20 checkset 的 A1 expectation 是 TESTING.md §4 的正向验收基线，**不因本问题而放宽**（P20 纪律：不修改 expectation 适配结果）；
- 修复验证 = 重跑 3-run baseline 后 A1 转为 stable PASS（satisfies_expected=True）→ 基线 VALID。

## 15. Validation

- ✅ **归因验证已完成**：lineage 重跑确认 `老二` 在 extraction 层缺失（无 mention 事件、raw extraction 零出现、原文唯一出现点 chunk15 的 27 角色不含它），recall/judge/registration 无事件（排除）；对照 `二老` 全链路正常（机制完好）；
- 修复验证（若采取修复）：A1 `PASS × 3` + P20 基线重建 `VALID`；
- 回归：P08/P09 相关 unit + integration 全绿。

## 16. Trade-offs

（待归因与修复设计时评估：如确认 D5-a extraction coverage——prompt 增强的边际收益与 descriptive 化风险，参照 P017 D5-a A/B 经验 `cd52844`。）

## 17. Decision

- **D-19 产品决策（2026-08-28，用户拍板）**：**单次、低显著性 mention 不要求稳定覆盖**——`老二`（全文仅 1 次出现的反说昵称）不再作为 correctness gate；接受 extraction coverage 模型能力边界，**不修复**；
- 落地：checkset v2（A1 收敛核心 gate + A7 观察项）、TESTING.md §4 同步、P20 基线按 v2 重建（旧 v1 基线 artifact 保留为历史）；
- 本问题**不在 P20 内修复**（P20 已 CLOSED）；无任何 pipeline / prompt / recall / judge / P16-b 修改。

## 18. Follow-up

1. ✅ **Task A 归因完成**（2026-08-28，lineage run novel `764795aa`）：`EXTRACTION_LAYER` / D5-a 形态（证据见 §8/§9/§10）；
2. ✅ **产品决策落地（D-19，2026-08-28）**：接受边界不修复；checkset v2（A1 收敛 + A7 观察）；TESTING.md §4 / DECISIONS D-19 / 本记录同步；
3. ✅ 针对 checkset v2 重建 3-run baseline（deepseek-v4-flash-0731，目标 VALID；若 A1 仍 FAIL 则为真实核心合并回归信号）；
4. 持续观察：A7（老二 吸收趋势）在换模型/未来 extraction 策略时的表现；若显著转好可评估升级回核心 gate（显式决策 + checkset bump）；
5. 同批信号：A2 天保/大老 variance 持续观察；**C3 爹爹 confirmed 已独立归因（EXTRACTION_LAYER，deepseek 5 次出现全漏提）并入 P017 D5-a 实例**（C3 保留 hard gate，v2 基线因 C3 保持 INVALID）——与本问题（老二/A1）同域（extraction coverage）不同 case，不并入本问题。

## 19. Current Limitation

- **`老二` 漏提 = 接受的 Known Limitation（D-19）**：单次低显著性 mention 不要求稳定覆盖；记录于 checkset v2 A7（observation 趋势可见），不阻塞基线 validity；
- 旧 checkset v1 基线保持 INVALID_NOT_REGRESSION_SAFE（历史事实，不覆盖）；v2 基线重建后作为现行回归基准；
- 同批 baseline 中的 variance 信号（A2、C3）未达立项标准，持续观察。

## 20. Do Not Reopen

- 若 A1 再 FAIL（修复后），先检查（按序）：
  1. **code regression**（recall/judge/extraction 相关改动）；
  2. **model change**（换模型 → 行为不同属正常，需重新评估）；
  3. **checkset 变化**（A1 expectation 是否被放宽——禁止）；
  4. **输入变化**（语料/切块配置）。
- 不要重复「A1 是 P20 framework 问题」的旧假设；不要在归因（Task A）前直接改 prompt/recall。
