# P008 — Entity Resolution：zero-overlap 分裂与 canonical 合并质量

- **Status**: 🔍 investigating
- **Severity**: High（消歧质量核心）
- **Domain**: ER 算法
- **Tags**: er, entity-resolution, zero-overlap, canonical-lock, text-recall, merge
- **First Seen**: V0.2 评估（天保↔大老、二老↔傩送）
- **Last Verified**: V0.2.3 真实《边城》评估（c4064416）+ V0.2.4 分析
- **Evidence Level**: HIGH（确定性机制缺口可稳定重现；合并质量受 judge 非确定性影响为 MEDIUM）
- **Decision Type**: EXPERIMENT_RESULT（重放确定性复现）+ DESIGN_DECISION（多层修复演进）
- **Related Problems**: P06（judge 非确定性，放大因素）；P09（mention hygiene，false merge 主因）；P10（共现顺序，已修）
- **Related Commits**: `c850bda`（chunk 预扫描）/ `9a72c24`（文本层召回）/ `ed4c388`（strong ranking）/ `73d383d`+（canonical merge b1/b2）
- **Related Evaluation Reports**: `docs/evaluation/2026-08-21-biancheng-er-eval.md`、`docs/evaluation/2026-08-21-biancheng-er-stability.md`

## 1. Context

《边城》真实评估：同一实体（天保/大老 = 大儿子）被拆到多个 canonical；后经 canonical merge 又出现反向问题（过度合并）。P08 是 ER 全链路的**合并质量问题**，不只是「召回失败」。

## 2. Symptom

- 天保/大老 实际同一人，分裂为 A={大儿子,[天保,天保大人]} 与 B={大老,[天保大老,儿子]}。
- V0.2.3 后：`两个儿子` 集合 canonical 虹吸 16 个 aliases（与 P09 重叠）。
- 同一人物图谱多个节点 / 搜索 alias 命中不完整。

## 3. Impact

- 图谱分裂或过度合并，关系失真。
- 搜索/统计被污染（P09 场景）。

## 4. Trigger

- 同一人物出现多个节点 / `'大老' IN p.aliases` 无记录但人物存在。
- 两个 canonical 的 alias 存在桥接名（天保大老）却未合并。
- 大量错误合并（先怀疑 P09 再 P08 再 P06）。

## 5. Timeline（V0.2 ER 完整演进）

- T1（V0.2.0 基础 ER）：mention→canonical 单向映射，alias judge 唯一决策点。
- T2（V0.2.1 extraction co-occurrence）：同 chunk 提取共现作为候选，但**顺序敏感**（P10）。
- T3（`c850bda` chunk pre-scan）：处理前预置本 chunk 已知名到 confirmed，消除顺序敏感（P10 修复）。
- T4（`9a72c24` text co-occurrence）：`_text_mentions` 用 chunk 原文已知 canonical/alias 作候选，绕开提取变异性；二老→傩送、天保大人→天保 成功。
- T5（V0.2.2 评估 765a7a13）：天保↔大老 仍分裂——首现锁定 + 无跨 canonical 合并路径 + 桥接名被 RECALL_TOP_K=5 截断。
- T6（`ed4c388` strong ranking V0.2.3-a）：strong（extraction+text confirmed）全保留、weak 只补位，桥接名候选完整进 judge。
- T7（V0.2.3-b1/b2 canonical merge）：bridge mention 双侧命中 established canonical → merge judge → merge_map → 单事务落库（`73d383d`/`5d51b83`/`4946102` 系列）。
- T8（V0.2.3 真实评估 c4064416）：**发现严重 false merge**——`两个儿子` 集合 canonical 虹吸 16 aliases。
- T9（V0.2.4 分析）：确认 false merge 主因是 **P09 mention hygiene**（extraction 把集合当 Person → 注册 canonical → alias judge 单候选吸收 → _index 膨胀 → text 扩散 → merge 桥接风暴）；P08 的合并机制本身被集合污染放大。
- T10（V0.2.4 实现）：MentionCategory + hygiene.py 落地，128 unit / 15 integration 通过；真实《边城》验证待执行。

## 6. Initial Hypothesis

「天保↔大老 分裂是候选召回失败」（**部分错误**——机制缺口存在，但「召回失败」措辞误导；候选层已证可行）。

## 7. Investigation Path

```text
Step 1  确定性文本扫描：目标人名在各 chunk 的出现集合（.tmp/chunk_ctx.txt）
Step 2  检查两 canonical 是否曾「同 chunk 被同时召回」
Step 3  重放 chunk 级 extract→resolve：mention→candidates→judge→canonical 全链路
Step 4  检查桥接名候选是否完整进入 judge（RECALL_TOP_K 截断？）
Step 5  重放可复现 = 机制缺口（P08）；重放分歧 = judge 非确定性（P06）
Step 6  false merge 场景：先查 mention category（P09）再查 merge judge
```

## 8. Experiments

### Experiment E1（确定性文本扫描）
- Input: 全书 chunk 文本
- Hypothesis: 大老/天保 是否存在共现机会
- Action: 关键词位置扫描（.tmp/chunk_ctx.txt）
- Result: 大老={9,10,11,12,14,16,17,19,20,21,22,24}；天保={6,7,10,11,17,...}；大老&大儿子 文本层从未共现
- Conclusion: chunk 9 大老 首现时物理上无法召回 天保 组 → 分裂机制缺口

### Experiment E2（重放 V0.2.2）
- Input: chunk 6/9/10/11 真实 extract 输出 + resolver
- Hypothesis: 候选完整时能否合并
- Action: 重放
- Result: chunk 11 天保大老 候选 [顺顺,兄弟,祖父,翠翠,小的] 无 天保（RECALL_TOP_K=5 截断）；chunk 10 天保大人 候选含 天保（文本层命中）→ 并入
- Conclusion: 文本层召回有效（二老/天保大人），但桥接名被 top-5 截断是缺口

### Experiment E3（V0.2.3-a strong ranking 后）
- Input: 同一 chunk 11
- Hypothesis: strong 全保留后候选完整
- Action: probe（.tmp 确定性脚本）
- Result: 天保大老 候选含 天保（A 组）+ 大老（B 组）
- Conclusion: 候选缺口修复；天保大老 桥接两侧可见

### Experiment E4（V0.2.3 真实评估 c4064416）
- Input: 全书真实 ingest（含 merge）
- Hypothesis: canonical merge 只合并真实同一实体
- Action: 观察合并结果
- Result: `两个儿子` 吸收 16 aliases；merge_map `{大老:二老, 二老:两个儿子, 天保大人:二老}`
- Conclusion: **false merge 主因 P09**（集合 canonical 虹吸）；P08 合并机制被污染放大

## 9. Evidence

- **code evidence**: `resolver.py` `_recall`（strong/weak 两段式）、`_text_mentions`、`decide_merges`、`apply_merges`。
- **log evidence**: 重放日志 `.tmp/replay_v022.txt`、`.tmp/chunk_ctx.txt`（未提交临时文件）。
- **database evidence**: 765a7a13（分裂：A/B 组）、c4064416（过度合并：两个儿子 16 aliases）。
- **test evidence**: `test_resolver.py` 23 项、`test_merge.py` 11 项、`test_merger.py` 21 项。
- **evaluation evidence**: `docs/evaluation/2026-08-21-biancheng-er-*.md`。

## 10. Root Cause

**P08 = zero-overlap 分裂 + canonical 合并质量**，两层：
1. **分裂（V0.2.2 及前）**：canonical 首现锁定永不重判；天保(chunk6)/大老(chunk9) 首现时互不在对方 chunk → 各自锁定；桥接名曾因 RECALL_TOP_K=5 截断看不到 A 组。
2. **过度合并（V0.2.3 起）**：canonical merge 的 bridge 规则在「候选含 ≥2 established canonical」时生成全量 pair；当集合 canonical（两个儿子，P09）进入候选，merge judge 全判 true → 虹吸。

## 11. Ruled-out Causes

- ~~「召回失败」~~：二老→傩送、天保大人→天保 证明候选召回可行；分裂是机制缺口非召回失败。
- ~~judge 非确定性是分裂主因~~：分裂可确定性重放复现（机制缺口），judge 非确定性只影响归组方向。
- ~~canonical merge 本身错误~~：merge 机制设计合理（b1 纯 decision + b2 单事务），问题在上游输入（集合 canonical）污染。

## 12. Failed Approaches

- 只靠字符重合/子串召回：zero-overlap 无解（已证伪）。
- 只靠 extraction 共现：提取漏提则无信号（已证伪）。
- 期望桥接名自动完成已分裂 canonical 合并而不保证候选完整（V0.2.2 截断证实不足）。
- 把单次运行结果当确定性（归组方向随提取变异性变化）。

## 13. Correct Approach

- ✅ chunk 预扫描（`c850bda`，P10 修复）。
- ✅ 文本层共现召回（`9a72c24`）：候选信号，judge 把关。
- ✅ strong/weak 两段式（`ed4c388`）：strong 全保留、weak 只补位，桥接名候选完整。
- ✅ canonical merge b1/b2（`73d383d`+）：bridge pair → merge judge → merge_map → 单事务。
- ✅ V0.2.4 mention hygiene（P09 落地）：集合 canonical 不再产生，false merge 源头消除。

## 14. Invariants

- 文本层命中只作候选信号，绝不直接建 alias（仍须 judge）。
- judge 每 chunk 一次批量判定；canonical 首现定主名、aliases 吸收保持（不重选 canonical）。
- 不跨 chunk / 不引入全局聚类 / 不做 embedding（既有边界）。
- canonical merge：b1 纯 decision（不改 known/_index/canonical_aliases），b2 唯一应用处。

## 15. Validation

- 分裂侧：二老↔傩送 合并成功（候选召回有效）；天保↔大老 分裂可由重放确定性解释。
- 合并侧：V0.2.4 后真实《边城》应不再出现 `两个儿子` 节点（待执行，unverified）。

## 16. Trade-offs

- 文本层召回引入「同名字不同人」候选噪声，依赖 judge 把关。
- 不跨 chunk 召回限制桥接能力。
- 首现锁定保证增量一致性，代价是后验合并需要新机制。

## 17. Decision

- ER 合并质量 = 多层修复：召回（P10/P08-a）→ 候选完整（V0.2.3-a）→ 跨 canonical 合并（V0.2.3-b）→ 输入卫生（V0.2.4/P09）。
- false merge 优先修 P09（已实现），bridge 候选限制暂缓（先验证 hygiene 效果）。

## 18. Follow-up

- V0.2.4 真实《边城》评估：验证 false merge 下降、`两个儿子` 不出现。
- 视评估结果决定是否做 merge bridge 候选限制（V0.2.4 明确暂缓）。
- 量化分裂/合并质量指标（候选完整进入 judge 的占比）。

## 19. Current Limitation

- P08 的「分裂」侧（真实零 overlap 且首现不同 chunk）在现行规则下仍可能发生——需要 merge 机制兜底，但 merge 依赖候选正确。
- canonical merge 的 bridge 全量 pair 规则未限制（暂缓）。

## 20. Do Not Reopen

- 再次出现分裂：先重放确认候选是否完整进 judge（机制缺口）vs judge 分歧（P06）vs 文本分布变化（输入）。
- 再次出现 false merge：**先查 P09（mention category/集合 canonical）再查 merge judge**；不要直接改 merge bridge 规则。
- 不要简单把问题定性为「召回失败」——候选召回已证可行。
