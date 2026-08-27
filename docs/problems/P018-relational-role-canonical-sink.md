# P018 — 正文 relational-role canonical sink：角色称谓被正文 canonical 吸收（P16-b）

- **Status**: 🔍 investigating（V0.2.5 真实评估首次干净观察；未立项设计）
- **Severity**: Medium（本次无跨人物错吸实证；机制脆弱，judge 误判时存在错吸风险）
- **Domain**: ER 算法 / judge 语义 / canonical 命名
- **Tags**: er, relational-role, sink, alias-absorption, judge, ambiguity, p16-b
- **First Seen**: V0.2.5 真实评估（job `1b7b7c1b`，novel `0ef3bd31`）
- **Last Verified**: 2026-08-26（EPUB 原文逐条核对 aliases 可解释性）
- **Evidence Level**: HIGH（父亲→顺顺 吸收存在且 8 个 aliases 全部可由顺顺解释）；MEDIUM（跨人物错吸为推断风险，本次未发生）
- **Decision Type**: EXPERIMENT_RESULT（真实评估观察）
- **Related Problems**: P16（P16-a 分离后残留的正文内机制）；P06（judge 判定方差）；P08（canonical 命名与分裂）
- **Related Commits**: 无（未立项）；前置 P16-a 修复 `c357e5f`
- **Related Evaluation Reports**: `docs/evaluation/2026-08-26-biancheng-v025-eval.md`

## 1. Context

P16-a（题记污染）修复后，`父亲` 不再由题记注册 canonical；真实评估（job `1b7b7c1b`）中 `父亲` 在**正文内**被吸收为 `顺顺` 的 alias。这是 P16-a 成功分离出的**正文内部**问题：relational-role 称谓（父亲/爸爸/爹爹）在正文中语义上指向真实人物（顺顺），经同 chunk 共现 + judge 吸收进该人物的 canonical。

## 2. Symptom

- `顺顺` canonical（mc=14）aliases=[爸爸, 父亲, 顺顺大哥, 顺顺船总, 船总顺顺, 中年人, 爹爹, 船总]。
- `父亲` canonical **不存在**（P16-a 生效）。
- 吸收发生在 ch5b（chunk6 成功）：「作父亲的当两个儿子很小时…」= 顺顺。

## 3. Impact

- 正向：角色称谓正确归并（爸爸/爹爹/中年人/船总 全部可解释为顺顺，EPUB 原文逐条核对 ch5/6/13/14/19/20/22）。
- 风险：同一 canonical 名「父亲」在正文不同语境语义不同（顺顺 / 翠翠之父 / 作渡船夫的父亲 ≥3 人）——本次 ch16/24 的「翠翠的父亲」**未**进入顺顺 aliases（未错吸），依赖 judge null + -b unresolved 兜底，机制脆弱。

## 4. Trigger

- 正文高频 relational-role 称谓（父亲/爸爸/爹爹/母亲…）与真实人物同 chunk 共现。
- judge 把「角色称谓 mention」判定为「人物 alias」（如 作父亲的 → 顺顺）。
- 同一称谓词在正文中指代多个不同人物（父亲 = 顺顺 / 翠翠之父）。

## 5. Timeline

- T1（V0.2.5 评估 1b7b7c1b）：顺顺 aliases 含 父亲/爸爸/爹爹/中年人/船总；父亲 canonical 不存在；翠翠的父亲 未进顺顺。
- T2（2026-08-26 归因）：EPUB 逐条核对 8 个 aliases 全部可解释；ch16/24「翠翠的父亲」未错吸（-b unresolved 或未提取兜住）。
- T3（2026-08-26）：确认为 P16-a 分离出的独立问题，单独立项（P018）。

## 6. Initial Hypothesis

「父亲→顺顺 是 judge 将角色称谓吸收进 canonical sink」——**成立**（ch5b「作父亲的」= 顺顺，吸收语义正确）；残留风险为「同一称谓跨人物错吸」。

## 7. Investigation Path

```text
Step 1  Neo4j：涉事 canonical 的 aliases/chapters（顺顺 8 aliases）
Step 2  EPUB 逐条定位每个 alias 的原文上下文（爸爸/爹爹/中年人/船总/父亲）
Step 3  判断每个 alias 是否可由 canonical 语义解释（正吸收 vs 错吸）
Step 4  检查跨人物风险点（翠翠的父亲 / 作渡船夫的父亲 是否被吸收）
Step 5  区分：吸收语义正确性（本次全对）vs 机制脆弱性（judge null + unresolved 兜底）
```

## 8. Experiments

### E1（aliases 可解释性核对，2026-08-26）
- Input: 顺顺 8 aliases + EPUB 全文上下文
- Result: 爸爸（ch5/6/14/22）= 天保/傩送/二老 之爸=顺顺；爹爹（ch13/20）= 大老/二老 之爹=顺顺；中年人（ch19）= 船总顺顺；船总/顺顺大哥/顺顺船总/船总顺顺 = 顺顺称谓；父亲（ch5b）= 作父亲的=顺顺——**全部可解释，无错吸**
- Conclusion: 本次吸收全部语义正确

### E2（跨人物风险点，2026-08-26）
- Input: 「翠翠的父亲」ch16/24 上下文 + 顺顺 aliases/chapters
- Result: 翠翠的父亲 未进入顺顺 aliases；顺顺 chapters 无 16
- Conclusion: 本次未发生错吸；由 judge null + -b unresolved 兜住（descriptive_unresolved=9 之一或未提取）

## 9. Evidence

- **database evidence**: novel `0ef3bd31`：顺顺 mc=14 aliases=8；父亲 canonical 不存在。
- **text evidence**: ch5b「作父亲的」；ch16/24「翠翠的父亲」；ch5/6/14/22 爸爸；ch13/20 爹爹；ch19 中年人——逐条原文。
- **code evidence**: `resolver.py`（同 chunk 共现候选 + judge 吸收 + -b unresolved 兜底）。
- **evaluation evidence**: `docs/evaluation/2026-08-26-biancheng-v025-eval.md` §4。

## 10. Root Cause

**正文内 relational-role 称谓与真实人物共用同一 mention 语义**：judge 依据 chunk 上下文（「作父亲的」与 顺顺 同 chunk 共现）把角色称谓判定为人物 alias。机制上**不区分**「称谓指向 canonical 的角色面」与「称谓独立指代另一人物」（翠翠的父亲）。当前依赖 judge 判定 + unresolved 兜底，无显式 relational-role 策略。

## 11. Ruled-out Causes

- ~~「题记污染残留（P16-a 未修复）」~~：父亲 canonical 不存在、顺顺 chapters 无题记章节 → P16-a 已闭环。
- ~~「本次发生跨人物错吸」~~：8 aliases 全部可解释，翠翠的父亲 未进顺顺。
- ~~「词表可解（把 父亲/爸爸/爹爹 加 generic）」~~：它们是顺顺 的合法正文称谓（语义正确吸收）；词表化会破坏正向归并。

## 12. Failed Approaches

- 无（尚未立项尝试修复；当前靠 judge null + unresolved 被动兜底）。

## 13. Correct Approach（待设计，未锁定）

候选方向（均需另立设计/Problem Record）：
- 区分「角色称谓吸收」与「跨人物错吸」：judge 输入增加关系/称谓上下文信号；或对高频 relational-role 称谓建立「先吸收后复核」机制。
- 显式记录 sink canonical 的角色面（父亲=顺顺 的 role alias），供后续跨人物冲突检测。
- **不承诺**：本轮不修改 resolver/judge 契约（见顶部报告声明）。

## 14. Invariants

- 不把 父亲/母亲/祖父 加入 generic 词表（P16 Do Not Reopen）。
- 不因 P16-b 未解决而判 P16-a/P17 失败。
- 不动 judge 契约 / merge bridge / Neo4j schema（需另立设计）。

## 15. Validation

- 当前为观察状态：下次评估继续统计 顺顺 类 canonical 的 role alias 吸收与错吸情况。
- 验收指标：role alias 吸收比例（正吸收 vs 错吸）；翠翠的父亲 类跨人物称谓是否持续被 unresolved 兜住。

## 16. Trade-offs

- 语义正确的角色称谓吸收（爸爸→顺顺）是**期望行为**——不能一刀切禁止。
- 错吸防护依赖 judge 判别力 + unresolved 兜底——脆弱但零额外成本。
- 若引入显式 role 策略，需权衡 judge 输入复杂度与额外 LLM 成本。

## 17. Decision

- 确认为独立问题（P018），**单独立项设计**；当前不修改代码。
- 与 P16-a（题记污染）边界清晰：P16-a 已闭环，P16-b 是正文内机制。

## 18. Follow-up

- 立项目设计（候选：role alias 记录 + 跨人物冲突检测；judge 上下文增强）。
- 下次真实评估继续观察（顺顺 类 sink 吸收与错吸率）。

## 19. Current Limitation

- 无显式 relational-role 策略；依赖 judge null + unresolved 兜底，机制脆弱。
- 「父亲」正文歧义（≥3 人）未建模；同 chunk 共现时 judge 误判即错吸。

## 20. Do Not Reopen

- 再次出现 父亲→顺顺 类吸收：先查是否为语义正确吸收（aliases 可解释性核对）→ 再查跨人物错吸（翠翠的父亲 类）→ 属于 P018，**不要**回退 P16-a/-b。
- 不要用「把 父亲/爸爸/爹爹 加入 generic 词表」修复（破坏正向归并）。
- 不要把 P018 与 P16/P17 合并为单一策略。
