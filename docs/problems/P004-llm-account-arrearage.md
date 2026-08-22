# P004 — 百炼账号欠费 / 账户状态异常（Arrearage）

- **Status**: ✅ resolved（账号层）
- **Severity**: High（LLM 全不可用）
- **Domain**: LLM / API 行为
- **Tags**: llm, arrearage, account, provider
- **First Seen**: V0.1/V0.2 评估阶段
- **Last Verified**: `36e8019` 诊断日志落地后
- **Evidence Level**: MEDIUM（多次观察支持，受外部账号状态影响，非可稳定重现的代码缺陷）
- **Decision Type**: EXPERIMENT_RESULT（单次探测确认 200）+ DESIGN_DECISION（诊断流程）
- **Related Problems**: P05（limit_requests，同域区分）
- **Related Commits**: `36e8019`（诊断日志）
- **Related Evaluation Reports**: 无独立报告（观察于真实评估期间）

## 1. Context

项目使用阿里云百炼（DashScope OpenAI 兼容模式）作为 LLM provider，`LLMClient` 统一封装 extract/judge/merge 调用。所有调用失败通过 `failed_blocks` 汇总进 job。

## 2. Symptom

全部 LLM 调用返回 HTTP 400，body 含 `"code":"Arrearage"` / `overdue-payment`。跨模型均 400，与模型名无关。

## 3. Impact

- 整本小说 ingest 无法进行（所有 chunk 抽取失败）。
- 若误判为代码 bug，会浪费大量排查时间。

## 4. Trigger

- `[llm]` 诊断日志出现 `stage=extract|judge status=400` 且 body 含 `Arrearage`。
- 全部 chunk 同时失败，且失败模式与代码路径无关（跨模型/跨接口一致）。

## 5. Timeline

- T1（V0.1/V0.2 评估期）：真实评估期间观察到全量 400 `Arrearage`。
- T2：当时 `failed_blocks` 只有 `unexpected:LLMError`（P07 未修），无法区分 400 类别。
- T3：`36e8019` 加入 `[llm]` 诊断日志（stage/status/body，不含 key）后，可区分 `Arrearage` vs `limit_requests` vs validation。
- T4：单次探测确认（任一模型应 200）→ 判定为账号层问题 → 充值解决。

## 6. Initial Hypothesis

「代码 bug 导致全部请求失败」（错误假设，已被证伪）。

## 7. Investigation Path

```text
Step 1  查看 [llm] 日志的 status/code/body
Step 2  识别 code=Arrearage → 账户层信号
Step 3  单次探测（任一模型）确认是否 200
Step 4  区分 Arrearage vs limit_requests vs validation
```

## 8. Experiments

### Experiment E1
- Environment: 真实评估期间，百炼账号
- Input: 任意 extract 调用
- Hypothesis: 代码路径异常（错误）
- Action: 检查 `[llm]` 日志 code 字段
- Result: `code=Arrearage`，跨模型一致
- Conclusion: 账号/账户层问题，与代码无关

## 9. Evidence

- **log evidence**: `[llm] stage=extract status=400 body={"error":{"code":"Arrearage",...}}`
- **code evidence**: `llm_client.py` `_log_error`（`36e8019` 引入）提供 status/body 摘要（不含 key）

## 10. Root Cause

阿里云百炼账号余额/欠费状态异常。账户层问题，跨模型均 400，与模型名、代码路径无关。

## 11. Ruled-out Causes

- ~~代码 bug 导致请求失败~~：单次探测证明账号恢复后代码正常。
- ~~模型名配置错误~~：跨模型一致 400，与模型名无关。

## 12. Failed Approaches

- 当成代码 bug 排查（浪费排查时间；无代码可修）。

## 13. Correct Approach

1. 先看 `[llm]` 诊断日志 `code` 字段。
2. `Arrearage` → 找用户充值，不改代码。
3. 区分 `Arrearage` vs `limit_requests`（P05）vs validation（P07）。

## 14. Invariants

- `[llm]` 日志必须记录 status/body 摘要（不含 key），否则无法区分失败类别。
- 账号层问题不得通过修改代码「修复」。

## 15. Validation

- 充值后全部调用恢复 200；同一代码路径未改动。

## 16. Trade-offs

- 诊断日志记录 response body 前 300 字符（`_log_error`），可能含请求细节但已排除 key。

## 17. Decision

- 账户问题走「单次探测确认 + 找用户充值」流程；`[llm]` 日志作为第一诊断入口（`36e8019`）。

## 18. Follow-up

- 无（账号层，随账户状态变化可复现；检测到 `Arrearage` 即走本记录流程）。

## 19. Current Limitation

- 欠费可能再次复现（账户余额用尽时）；本记录只提供诊断流程，不改变 provider 侧行为。

## 20. Do Not Reopen

- 再次出现全量 400：先看 `[llm]` 日志 `code`——`Arrearage` 直接走账户检查，**不要**启动代码级调查。
- 不要重复「改代码修复 400」的错误做法。
- 只有当 `code` 不是 `Arrearage` 且非 `limit_requests`（P05）时，才考虑代码问题。
