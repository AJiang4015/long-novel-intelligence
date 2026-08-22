# P006 — Judge 判定非确定性 + 过度合并（LLM 概率性 vs 确定性算法问题）

- **Status**: 🔍 investigating
- **Severity**: High（消歧质量核心）
- **Domain**: LLM 行为 / ER 算法
- **Tags**: llm, judge, nondeterminism, over-merge, er
- **First Seen**: V0.1/V0.2 评估阶段
- **Last Verified**: V0.2.3 真实《边城》评估（c4064416 过度合并分析）
- **Evidence Level**: MEDIUM（多次实验支持，受 LLM 非确定性影响，无法稳定重现同一判定）
- **Decision Type**: EXPERIMENT_RESULT（重放分歧）+ DESIGN_DECISION（保持 judge 为唯一决策点）
- **Related Problems**: P04（账户）、P05（限流）、P08（候选召回）、P09（mention hygiene）
- **Related Commits**: `685d019`（稳定性评估）/ `36e8019`（诊断日志）
- **Related Evaluation Reports**: `docs/evaluation/2026-08-21-biancheng-er-stability.md`

## 1. Context

Entity Resolution 的 alias judge 与 canonical merge judge 均由 LLM 承担（`llm_client.judge_aliases` / `judge_merges`）。judge 输出决定 mention 归入哪个 canonical、以及两个 established canonical 是否合并。LLM 判定具有概率性。

## 2. Symptom

- 同一 chunk 同一候选集，不同运行 judge 判「相同」或「不同」（二老→傩送 vs 二老→null）。
- 同一次 ingest 内，重放可合并（二老→傩送）但原运行判不同。
- judge 会把泛指词（水上人/轻薄男子）误并入人物节点。
- V0.2.3 后：canonical merge judge 把桥接 mention 触发的 pair 全判 true，导致 16 个 alias 并入 `两个儿子`（false merge）。

## 3. Impact

- 同一小说两次 ingest 得到不同合并结果，图谱不稳定。
- 泛指词并入人物 → 伪人物/错误关系。
- canonical merge judge 过度合并 → 严重实体污染（c4064416）。

## 4. Trigger

- 同样输入的 judge 输出不同（跨运行）。
- 同一小说两次 ingest 结果不一致。
- 人物节点出现泛指词（水上人/轻薄男子）或集合词（两个儿子）。
- 评估结果与重放结果分歧。

## 5. Timeline

- T1（V0.1/V0.2 评估）：首次观察到同一输入 judge 输出不同（二老↔傩送 重放分歧）。
- T2（`685d019`）：稳定性评估记录 judge 跨运行分歧。
- T3（`36e8019`）：诊断日志落地，可区分 judge failure 类别。
- T4（V0.2.3 真实评估 c4064416）：canonical merge judge 对 `天保大老` 触发的 6 个 pair 全判 true → 大老/二老/天保大人 并入 `两个儿子`。
- T5（V0.2.4 分析）：确认 false merge 的**主因是 mention hygiene（P09）+ 候选扩散（P08 机制）**，judge 非确定性是放大因素而非根因。

## 6. Initial Hypothesis

「ER 失败主要归因于 judge 不稳定」（**部分错误**——见 Ruled-out Causes）。

## 7. Investigation Path

```text
Step 1  确认是 LLM 非确定性，而不是限流/欠费/召回/卫生问题：
        - [llm] 日志 code：429=limit_requests（P05）、400 Arrearage（P04）
        - 同输入重放：输出不同 = 非确定性（P06）
        - 候选是否完整进 judge（P08 机制缺口）
        - mention 是否是集合/泛指（P09 hygiene）
Step 2  对照 Environment Baseline（commit/model/temperature/concurrency，TESTING.md §9）
Step 3  评估多次取趋势，不以单次输出为 ground truth
```

### 四类问题的区分（P06 ≠ 其他）

| 现象 | 类别 | 处理 |
|---|---|---|
| 同输入不同输出 | LLM 非确定性（P06） | 多次评估取趋势；prompt 约束；测试用 mock judge |
| 429 limit_requests | API 限流（P05） | 查账户 + concurrency A/B |
| 400 Arrearage | 账号欠费（P04） | 找用户充值，不改代码 |
| 候选缺项/截断 | Candidate recall（P08） | 查 `_recall` 三层与 RECALL_TOP_K |
| 集合/泛指入实体 | Mention hygiene（P09） | category 过滤 + resolver 决策 |
| canonical merge 全并入 | Merge judge 过度合并（P06 放大 + P08/P09 上游） | hygiene 先修，bridge 规则后评估 |

## 8. Experiments

### Experiment E1（重放分歧）
- Environment: 同一 chunk 文本 + 同一候选集，两次 judge 调用
- Input: 二老 候选 [傩送]
- Hypothesis: judge 结果可复现（错误）
- Action: 重放
- Result: 一次判 二老→傩送，另一次判 null
- Conclusion: judge 判定概率性，不可作为确定性 ground truth

### Experiment E2（V0.2.3 merge judge 全并入）
- Environment: c4064416 真实 ingest，`天保大老` mention
- Input: 候选 [大老, 两个儿子, 天保大人, 二老]（4 个 established canonical）
- Hypothesis: merge judge 会拒绝明显不相关的 pair
- Action: 观察 decide_merges 输出
- Result: 6 个 pair 全判 merge=true，conf 0.9+
- Conclusion: merge judge 在候选含集合 canonical 时过度合并（上游 P09 是主因，judge 是放大）

## 9. Evidence

- **experiment evidence**: E1（重放分歧）、E2（merge 全并入）。
- **log evidence**: `[llm] stage=judge status=200 body=...`（`36e8019`）。
- **database evidence**: c4064416 `两个儿子` 节点 16 aliases（与 P09 共享证据）。
- **evaluation evidence**: `docs/evaluation/2026-08-21-biancheng-er-stability.md`。

## 10. Root Cause

- LLM 判定概率性（temperature 0.1 仍波动）。
- judge prompt 对「称谓 vs 本名」「泛指 vs 人名」「集合 vs 个体」约束不足。
- **注意**：c4064416 的严重 false merge 主因是 P09（集合 canonical 虹吸）+ P08（候选扩散），judge 非确定性是放大因素——**不能把所有 ER 失败都归因于 P06**。

## 11. Ruled-out Causes

- ~~ER 失败主因是 judge 不稳定~~：V0.2.4 分析证明 c4064416 false merge 主因是 P09 集合 canonical 虹吸；judge 只是执行了「候选只有 两个儿子」时的错误合并。
- ~~judge 非确定性 = 限流/欠费~~：P06 ≠ P05 ≠ P04（code 区分）。

## 12. Failed Approaches

- 假设 judge 结果可复现（已证伪）。
- 把单次 judge 输出当 ground truth 写死进测试（AGENTS.md §15 Don't）。
- 把「ER 失败」一律归因于 judge（掩盖 P08/P09 机制缺口）。

## 13. Correct Approach

- 评估多次取趋势；每次真实评估记录 Environment Baseline（TESTING.md §9）。
- 单元/集成测试用 mock judge，不依赖真实 LLM。
- 消歧结果差异先对照诊断日志区分：非确定性（P06）/ 限流（P05）/ 欠费（P04）/ 候选召回（P08）/ mention hygiene（P09）。
- 保持 judge 为唯一合并决策点（现有设计）。

## 14. Invariants

- judge 每 chunk 一次批量判定；判定失败 → mention 独立 canonical + failed_blocks（预期行为）。
- 候选必须来自 `_recall`（禁止绕过 judge 直接建 alias）。
- 文本层命中只作候选信号，绝不直接认定同一人。
- merge judge 失败/低置信 → 不 merge（安全默认）。

## 15. Validation

- 多次运行评估统计合并率趋势；差异能用 Baseline 解释即为「已知非确定性」而非回归。
- V0.2.4 后：真实《边城》评估应验证 false merge 显著下降（待执行，unverified）。

## 16. Trade-offs

- 无法根除 LLM 非确定性；只能降低影响（prompt 约束、多次评估、mock 测试、上游 hygiene 修复）。

## 17. Decision

- 保持 judge 为唯一合并决策点；诊断日志先行；测试 mock。
- **不把 ER 失败一律归因于 P06**——先路由到 P04/P05/P08/P09。

## 18. Follow-up

- judge prompt 增强（称谓/泛指/集合约束）。
- merge judge 的 bridge 候选限制（候选含 ≥2 canonical 时的 pair 上限）——V0.2.4 明确暂缓，先验证 hygiene 效果。
- V0.2.4 真实《边城》评估后重新评估 judge 影响。

## 19. Current Limitation

- judge 非确定性无法消除；跨运行结果差异是已知限制。
- 无 judge 一致性度量基线（多次评估趋势未量化）。

## 20. Do Not Reopen

- 再次出现消歧差异：先走 Diagnostic Routing 区分 P04/P05/P08/P09/P06，**不要**默认归因 judge。
- 不要重复「把单次 judge 输出当 ground truth」。
- 只有在新证据（如 judge prompt 变更后的对照实验）出现时才重新评估 judge 根因。
