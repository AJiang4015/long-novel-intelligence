# P005 — 429 / limit_requests 限流诊断规则

- **Status**: ✅ resolved（诊断规则已确立）
- **Severity**: High（LLM 大面积失败）
- **Domain**: LLM / API 行为
- **Tags**: llm, rate-limit, concurrency, account
- **First Seen**: V0.2 真实评估期间（27 chunk 大面积失败）
- **Last Verified**: 账号恢复后重放/评估（concurrency=1 稳定成功）
- **Evidence Level**: MEDIUM（多次实验支持，但受 LLM 非确定性/账户状态/配额影响）
- **Decision Type**: DESIGN_DECISION（429 诊断规则）+ EXPERIMENT_RESULT（concurrency=1 稳定成功）
- **Related Problems**: P04（Arrearage，同域强相关——历史事故中两者混淆）
- **Related Commits**: `36e8019`（诊断日志）
- **Related Evaluation Reports**: 无独立报告（观察于真实评估期间）

## 1. Context

真实评估《边城》期间，27 chunk 大面积失败。当时 `LLM_CONCURRENCY=4`，`failed_blocks` 显示大量失败，`[llm]` 日志含 `limit_requests`。

## 2. Symptom

- HTTP 429 / body `code=limit_requests`。
- 并发 4 时 27 chunk 大面积失败；并发 1 后 0 失败。

## 3. Impact

- 整本 ingest 大面积失败，评估无法完成。
- 若错误归因于 concurrency，会永久降低配置并掩盖真实根因（账户状态）。

## 4. Trigger

- `[llm]` 日志出现 `status=429` 或 `code=limit_requests`。
- 大量 chunk 同时失败且失败模式与并发相关。

## 5. Timeline

- T1（V0.2 评估期）：`LLM_CONCURRENCY=4`，27 chunk 大面积失败，日志含 `limit_requests`。
- T2：临时降 `LLM_CONCURRENCY=1` → 0 失败。
- T3：**同时期存在百炼账号欠费/账户状态异常**（P04），`Arrearage` 与 `limit_requests` 混现。
- T4：账号恢复正常后，`concurrency=1` 稳定完成；**历史证据显示账号余额正常时 `concurrency=4` 曾正常运行**。
- T5（V0.2.4 重构）：P05 结论修正为「429 诊断规则」，删除「真实评估必须 concurrency=1」的错误结论。

## 6. Initial Hypothesis

「`LLM_CONCURRENCY=4` 是 429 根因，必须永久降为 1」（**错误假设，已被证伪**）。

## 7. Investigation Path

```text
Step 1  查看 [llm] 日志 status/code：429=limit_requests（P05）、400 Arrearage（P04）
Step 2  确认账号状态（欠费/余额），排除 P04
Step 3  账号正常时再做 concurrency A/B（1/2/4）实验
Step 4  仅当「账号正常 + 降并发 429 消失 + 提并发复现」时才能判定并发为主因
```

## 8. Experiments

### Experiment E1（历史）
- Environment: 百炼账号异常期间，`LLM_CONCURRENCY=4`
- Input: 27 chunk 抽取
- Hypothesis: concurrency=4 导致限流（错误）
- Action: 观察 `[llm]` 日志
- Result: `limit_requests` 与 `Arrearage` 混现
- Conclusion: **不能仅凭该次事故证明 concurrency=4 是根因**（账户状态为混淆变量）

### Experiment E2（历史）
- Environment: 账号恢复后，`LLM_CONCURRENCY=1`
- Input: 27 chunk 抽取
- Hypothesis: concurrency=1 可稳定
- Action: 运行
- Result: 0 失败
- Conclusion: concurrency=1 当时稳定成功，**但不能证明默认必须为 1**

### Experiment E3（历史）
- Environment: 账号余额正常时，`LLM_CONCURRENCY=4`
- Input: 真实评估
- Hypothesis: 验证 concurrency=4 是否可用（错误假设的反证）
- Action: 运行
- Result: 正常完成
- Conclusion: 账号正常时 concurrency=4 可以正常运行

## 9. Evidence

- **log evidence**: `[llm]` 日志 `status=429 code=limit_requests`（P07/`36e8019` 后可区分）。
- **experiment evidence**: E1（混现）/ E2（concurrency=1 稳定）/ E3（concurrency=4 正常）三组实验。
- **database evidence**: 无（本问题是调用侧）。

## 10. Root Cause

429 / `limit_requests` 是 **provider 限流信号**，受多因素影响：账户状态（P04 混淆）、模型配额（RPM/TPM）、并发、网络。历史大面积失败期间账户状态异常，**无法将并发 4 认定为唯一根因**。

## 11. Ruled-out Causes

- ~~`LLM_CONCURRENCY=4` 必然导致 429~~：E3 证明账号正常时 concurrency=4 可正常运行。
- ~~真实评估必须 concurrency=1~~：这是基于混淆实验的错误结论，已删除。

## 12. Failed Approaches

- 把「并发 4 → 27 失败」当作确定因果，永久把 `LLM_CONCURRENCY` 降为 1（错误做法，掩盖账户根因）。
- 未检查 `[llm]` 日志 code/status 就改代码（错误做法）。
- 把单次实验结果写成固定配置规则（错误做法）。

## 13. Correct Approach

> 遇到 429 时先检查账户状态和 `[llm]` diagnostic code，再做 concurrency A/B；不得因为一次事故永久把 concurrency 降到 1。

1. 先看 `[llm]` 日志确认是 `limit_requests`。
2. 确认账号余额/欠费状态（P04 排除）。
3. 账号正常前提下做 concurrency A/B（1/2/4）。
4. 保持项目默认并发配置；仅当可复现限流时临时调低并记录实验。

## 14. Invariants

- `LLM_CONCURRENCY` 默认值不因一次 429 事故永久降为 1。
- 任何 429 排查必须先看 `[llm]` 日志 code + 账户状态，再谈并发。
- 真实评估记录 Environment Baseline（TESTING.md §9），保证实验可对照。

## 15. Validation

- 账号恢复后 concurrency=1 稳定完成（E2）；账号正常时 concurrency=4 曾成功（E3）。
- 诊断规则已写入 PROBLEM.md Diagnostic Routing（P04/P05 路由）。

## 16. Trade-offs

- 不永久降并发意味着账号正常时可能再次遇到真实限流——但可通过 A/B 实验定位，而非一刀切。

## 17. Decision

- P05 = 「429 限流诊断规则」，**不是**「并发 4 导致限流」。
- 429 是服务端/账号侧限流信号；诊断顺序 = code → 账户 → concurrency A/B。

## 18. Follow-up

- 可做一次干净的 concurrency A/B（账号正常、同模型、同输入），明确并发对 429 的影响边界（尚未执行，标记 unverified）。

## 19. Current Limitation

- 无干净的 A/B 对照实验（历史实验受账户状态混淆）；并发对 429 的精确影响边界为 unverified。
- 模型配额（RPM/TPM）随 provider 策略变化，不可静态断言。

## 20. Do Not Reopen

- 再次出现 429：先看 `[llm]` 日志 code → `limit_requests` → 查账户状态（P04）→ 再做 concurrency A/B。
- **不要**重复「看到 429 就永久降并发到 1」的旧做法。
- **不要**把「concurrency=4 必然导致 429」当作事实——它已被证伪（Ruled-out Causes）。
- 只有在新证据（干净 A/B）出现时才需要重新评估并发边界。
