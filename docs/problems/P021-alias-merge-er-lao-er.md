# P021 — 《边城》正向合并：`老二` 未并入 `傩送` aliases（deepseek-v4-flash-0731 稳定失败）

- **Status**: 🔍 investigating（baseline 观测成立；**归因待 lineage Task A**——extraction coverage vs judge 判定，D-11「Task A 先于 Task B」）
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

- **(a) extraction coverage 缺失（D5-a 形态）**：`老二` 未被 LLM 提取为 mention → 根本未进入 pipeline；
- **(b) judge 判 null / 判不同（P06）**：`老二` 被提取，但 judge 未将其 resolves_to 傩送；
- **(c) recall 未召回（P08）**：`老二` 出现 chunk 与 傩送 无共现且无桥接，未产生候选（零共享字场景）。

## 7. Investigation Path

```text
Step 1  lineage 观测重跑（ER_LINEAGE=1，1 run）：确认 老二 mention 是否进入 extraction 输出
Step 2  (a) 若未提取 → extraction coverage（D5-a 形态，P017 域）→ prompt/模型域
Step 3  (b) 若已提取 → 查 recall 事件（是否进入候选集）→ judge 事件（resolves_to / null）归层
Step 4  原文定位：老二 在《边城》中出现章节（evidence dump / 确定性文本检索）→ 与该 canonical chapters 对照
```

## 8. Experiments

（设计阶段，尚未实施。计划：lineage 归因重跑 + 原文证据核对；不凭经验改代码——D-11。）

## 9. Evidence

- **baseline artifact**（`biancheng-2026-08-28-deepseek-v4-flash-0731.json`）：`per_check.A1 = {"classification": "stable", "satisfies_expected": false, "outcome_distribution": {"FAIL": 3}}`；`baseline_status = INVALID_NOT_REGRESSION_SAFE`；`stable_failures = [A1]`；
- **3 个 run 的 result.json**：A1 reason 恒为 `aliases 缺失: ['老二']`；
- **图结构证据（Neo4j 直查，2026-08-28）**：3 个 run 中 傩送 均为**单一 canonical**（mc=15，chapters=[5,6,7,8,12,13,15,17,18,19,20,21,22,24]，三 run 一致），`二老` ∈ aliases，`老二` ∉ aliases——**排除分裂**（非 P08 零共享字分裂）；问题形态 = 老二 这一别名丢失；
- **1-run 佐证**（novel `f4c78364`，同模型）：A1 同 FAIL——行为跨 4 次运行一致。

## 10. Root Cause

**未定**。已排除「分裂」（单一 canonical 存在）；候选集中于 extraction coverage（D5-a）/ judge 判定（P06）/ recall（P08），需 lineage 归因（§7 Step 1-3）。

## 11. Ruled-out Causes

- ~~canonical 分裂（P08 零共享字分裂）~~：图结构显示单一 canonical（mc=15，三 run 一致），非分裂。
- ~~A1 checkset 定义错误~~：expectation 与 TESTING.md §4 正向 1 组一致（老二 是既有验证成员）；1-run 与 3-run 行为一致。

## 12. Failed Approaches

- 无（新立项，归因前无修复方案）。

## 13. Correct Approach

按 PROCESS.md 纪律：**归因（lineage Task A，D-11）→ 归到拥有该决策的层 → Spec → Review → 修复 → 重跑 3-run baseline 重建 VALID 基线**。候选修复面（归因后选）：prompt 增强（D5-a）/ recall 结构规则 / judge 判定对齐；**不扩 generic 词表（D-7）、不引入 classifier（D-10）、不修改 P16-b**。

## 14. Invariants

- 不把 老二 加入 generic 词表或任何词表 hack（D-7）；
- 不引入 classifier 绕过 D5（D-10）；
- 不修改 P16/P17/P18 冻结语义（D-6/D-9）；
- P20 checkset 的 A1 expectation 是 TESTING.md §4 的正向验收基线，**不因本问题而放宽**（P20 纪律：不修改 expectation 适配结果）；
- 修复验证 = 重跑 3-run baseline 后 A1 转为 stable PASS（satisfies_expected=True）→ 基线 VALID。

## 15. Validation

- 归因验证：lineage 重跑确认 老二 在 extraction / recall / judge 三层的去向（唯一证据路径）；
- 修复验证：A1 `PASS × 3` + P20 基线重建 `VALID`；
- 回归：P08/P09 相关 unit + integration 全绿。

## 16. Trade-offs

（待归因与修复设计时评估：如确认 D5-a extraction coverage——prompt 增强的边际收益与 descriptive 化风险，参照 P017 D5-a A/B 经验 `cd52844`。）

## 17. Decision

- **A1 属 ER 质量缺口，不在 P20 内修复**（P20 约束 4：先建立质量基线，不修质量问题）；P20 已收尾，基线 INVALID 状态如实保留；
- 归因未定前**不做任何代码修改**（D-11）。

## 18. Follow-up

1. Task A：lineage 观测（ER_LINEAGE=1）重跑 1 run，归因 老二 在 extraction/recall/judge 层的去向；
2. 原文证据核对（老二 出现章节 ↔ canonical chapters 差异）；
3. 归因结论 → 按 D-12 决定是否再拆分（若 extraction coverage 则并入 P017 D5-a 域评估，若 judge 则 P06 域）；
4. 修复后重跑 3-run baseline → A1 stable PASS → P20 基线重建 VALID。

## 19. Current Limitation

- 归因未定（extraction coverage vs judge vs recall）；
- P20 基线保持 INVALID（A1 修复前不可作回归比较）；
- 同批基线中的 variance 信号（A2 天保/大老 2/3、C3 爹爹 confirmed 1/3）未达立项标准，持续观察（不并入本问题）。

## 20. Do Not Reopen

- 若 A1 再 FAIL（修复后），先检查（按序）：
  1. **code regression**（recall/judge/extraction 相关改动）；
  2. **model change**（换模型 → 行为不同属正常，需重新评估）；
  3. **checkset 变化**（A1 expectation 是否被放宽——禁止）；
  4. **输入变化**（语料/切块配置）。
- 不要重复「A1 是 P20 framework 问题」的旧假设；不要在归因（Task A）前直接改 prompt/recall。
