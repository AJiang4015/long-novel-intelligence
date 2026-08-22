# P10 — 同 chunk 共现召回顺序敏感

- **Status**: ✅ resolved
- **Severity**: High（修复前阻断同 chunk 合并）
- **Domain**: ER 算法
- **Tags**: er, co-occurrence, ordering, pre-scan
- **First Seen**: V0.2 开发
- **Last Verified**: `c850bda` 修复后回归通过
- **Evidence Level**: HIGH（确定性机制，重放可稳定复现）
- **Decision Type**: EXPERIMENT_RESULT（顺序差异确定性复现）+ DESIGN_DECISION（chunk 预扫描）
- **Related Problems**: P08（文本层召回叠加于其上）
- **Related Commits**: `c850bda`
- **Related Evaluation Reports**: 无独立报告（开发期确定性复现）

## 1. Symptom

未知 mention 出现在已知名之前时丢失共现候选（top-5 被字符重合占满）。

## 2. User-visible / System Impact

- 同 chunk 内同一人物以不同名出现但未合并 → 图谱分裂（与 P08 同症状但不同机制：顺序 vs 首现锁定）。

## 3. Trigger

- 同 chunk 内 A 名在 B 名之前出现，A 未召回 B。
- 候选 top-5 全被字符重合占满，共现候选缺失。

## 4. Minimal Reproduction

chunk 提取输出 [未知M, 已知K]（M 在 K 前）：处理 M 时 `confirmed` 仍为空 → 无共现候选。

## 5. Investigation Path

```text
Step 1  检查 resolve() 是否在遍历前预扫描 chunk_names → confirmed
Step 2  若 confirmed 随处理顺序累积 → 顺序敏感复现
Step 3  验证 c850bda 预扫描逻辑是否仍在
```

## 5.1 Timeline

- T1（V0.2 开发）：未知 mention 出现在已知名之前时丢失共现候选（top-5 被字符重合占满）。
- T2：确认 `confirmed` 从空集随处理顺序累积。
- T3（`c850bda`）：chunk 预扫描修复——处理前把本 chunk 已知名预置进 confirmed。

## 5.2 Experiments

### Experiment E1
- Environment: resolver，顺序敏感场景
- Input: chunk 提取 [未知M, 已知K]（M 在前）
- Hypothesis: confirmed 随顺序累积（错误行为）
- Action: 记录 M 的候选
- Result: M 无共现候选（K 尚未处理）
- Conclusion: 顺序敏感成立，需预扫描

## 5.3 Ruled-out Causes

- ~~共现与处理顺序无关~~：E1 证明顺序敏感，假设证伪。

## 5.4 Initial Hypothesis

「候选丢失是召回公式问题」→ 实际是状态累积时机问题。

## 6. Evidence

- 修复 commit `c850bda`：处理前把本 chunk 中已知名预置进 `confirmed`。

## 7. Root Cause

`confirmed` 从空集随处理顺序累积，未知 mention 先处理时看不到后出现的已知名。

## 8. Why

逐名字顺序处理是自然实现，但共现语义是「同 chunk 整体」、与处理顺序无关——状态累积时机与语义不匹配。

## 9. Failed Approaches

- 假设共现与处理顺序无关（已证伪）。

## 10. Correct Approach

chunk 预扫描：处理前把本 chunk 中已知名预置进 `confirmed`（`resolve()` 开头 `chunk_names`/`confirmed` 预置）。

## 11. Invariants

- 同 chunk 共现候选与处理顺序无关（预扫描必须保持在 `resolve()` 开头）。
- `confirmed` 预置后仍只含本 chunk 提取输出的已知 canonical。

## 12. Validation

- 顺序敏感回归测试通过；共现候选不再依赖名字处理先后。

## 13. Trade-offs / Limitations

- 预扫描依赖提取输出完整性；提取漏提仍无信号（由 P08 文本层召回弥补）。

## 14. Decision

- 采纳 chunk 预扫描方案（`c850bda`）。

## 15. Follow-up

- 无（已闭环；文本层召回在其上叠加，见 P08）。

## 16. Do Not Reopen Without Evidence

若再次出现顺序敏感症状：

1. 确认 c850bda 预扫描代码是否仍在 `resolve()` 开头（代码回退）。
2. 检查是否新代码在预扫描前消费了 `confirmed`。
3. 检查 RECALL_TOP_K 是否被改小导致截断（配置变化）。
4. 不要改回「按处理顺序累积」方案。
