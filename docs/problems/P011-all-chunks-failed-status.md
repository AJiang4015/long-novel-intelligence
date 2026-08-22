# P011 — 全部 chunk 失败时 job 状态应为 failed

- **Status**: 🔍 investigating
- **Severity**: Medium（状态机正确性）
- **Domain**: 流程 / job 状态机
- **Tags**: job-status, state-machine, spec
- **First Seen**: V0.2 集成
- **Last Verified**: investigating（代码变更未授权）
- **Evidence Level**: HIGH（27/27 失败场景可复现）
- **Decision Type**: FACT（症状与 spec 定义一致）+ DESIGN_DECISION（待定修复方向）
- **Related Problems**: 无直接关联（独立状态机问题）
- **Related Commits**: 未提交修复
- **Related Evaluation Reports**: 无（观察于真实评估期间，LLM 全失败场景）

## 1. Context

`_run_ingest`（novels.py）后台任务终态判定：按 `failed_blocks` 非空判 `completed_with_errors`，`failed` 仅在异常路径设置。spec §5.1 定义「全部失败 → failed」。

## 2. Symptom

27/27 chunk 失败时 job 仍为 `completed_with_errors`，而非 spec 定义的 `failed`。

## 3. Impact

- 前端显示「部分成功」但实际 0 数据，误导用户。

## 4. Trigger

- job 状态为 `completed_with_errors` 但 failed_blocks 数量 = 总 chunk 数。
- 前端出现「部分成功」但图谱为空。

## 5. Timeline

- T1（V0.2 集成）：观察到 27/27 chunk 失败但 job 为 `completed_with_errors`。
- T2（P11 记录）：确认 `_run_ingest` 只按 failed_blocks 非空判部分失败，无「全部失败 → failed」分支。
- T3（investigating）：修复方向已定（补终态分支），代码变更未授权。

## 6. Initial Hypothesis

「有数据输出即状态正确」→ 实际 27/27 失败也有 completed_with_errors，假设证伪。

## 7. Investigation Path

```text
Step 1  检查 _run_ingest 终态判定逻辑
Step 2  确认 failed 仅在异常路径设置；failed_blocks 非空 → completed_with_errors
Step 3  对照 spec §5.1 判定规则
```

## 8. Experiments

### Experiment E1
- Environment: 真实评估期间 LLM 全失败（账户/限流，见 P04/P05）
- Input: 27 chunk 全部失败
- Hypothesis: job 终态应为 failed（spec）
- Action: 观察 job 状态
- Result: `completed_with_errors`
- Conclusion: 终态判定缺「全部失败」分支，症状与 spec 不一致

## 9. Evidence

- **database evidence**: job 状态观察（completed_with_errors）。
- **code evidence**: `_run_ingest` 终态判定（novels.py）。

## 10. Root Cause

`_run_ingest` 只按 failed_blocks 非空判 `completed_with_errors`；`failed` 仅在异常路径设置，无「全部失败 → failed」分支。

## 11. Ruled-out Causes

- ~~有数据输出 = 状态正确~~：27/27 失败也有 completed_with_errors，证伪。

## 12. Failed Approaches

- 以「有数据输出」倒推状态正确（已证伪）。

## 13. Correct Approach（待定）

- 终态判定补「全部 chunk 失败 → failed」（代码变更未授权）。

## 14. Invariants

- failed_blocks 统计语义不变；`completed_with_errors` 仍表示「部分成功」。

## 15. Validation

- 构造全部失败场景，断言 job 终态 = `failed`；部分失败场景仍 = `completed_with_errors`。

## 16. Trade-offs

- 需明确「全部失败」边界（chunk 数 > 0 且失败数 = chunk 数）。
- 与 `merge_failures`/`mention_hygiene` 等新统计无关（P11 只关心 chunk 失败计数）。

## 17. Decision

- 待用户授权实现；当前记录为 investigating。

## 18. Follow-up

- 实现 + 回归测试（全部失败 → failed；部分失败 → completed_with_errors）。

## 19. Current Limitation

- 未实现（代码变更未授权）。

## 20. Do Not Reopen

- 状态问题再次出现：先确认终态判定代码是否已补「全部失败」分支（代码变化），再检查失败统计口径是否变化。
- 不要重复「以有数据输出倒推状态正确」的旧假设。
- 只有实现后仍出现状态错误时重新打开。
