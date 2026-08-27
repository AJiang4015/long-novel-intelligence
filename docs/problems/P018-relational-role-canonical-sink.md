# P018 — 正文 relational-role canonical sink：角色称谓被正文 canonical 吸收（P16-b）

- **Status**: 🔍 investigating（设计评审中：候选 A+B 已细化，未实现）
- **Severity**: Medium（本次无跨人物错吸实证；机制脆弱，judge 误判时存在错吸风险）
- **Domain**: ER 算法 / judge 语义 / canonical 命名
- **Tags**: er, relational-role, sink, alias-absorption, judge, ambiguity, p16-b, role-admission
- **First Seen**: V0.2.5 真实评估（job `1b7b7c1b`，novel `0ef3bd31`）
- **Last Verified**: 2026-08-26（EPUB 原文逐条核对 aliases 可解释性 + mock 实验 M1-M5）
- **Evidence Level**: HIGH（父亲→顺顺 吸收存在且 8 个 aliases 全部可由顺顺解释；M5 错吸可复现）；MEDIUM（错吸发生率为推断，依赖 judge 判别力）
- **Decision Type**: EXPERIMENT_RESULT（真实评估观察 + mock 复现）+ DESIGN_DECISION（V0.2.6 候选 A+B：role alias 证据准入）
- **Related Problems**: P16（P16-a 分离后残留的正文内机制）；P06（judge 判定方差）；P08（canonical 命名与分裂）；P17（共用注册缝，策略独立）
- **Related Commits**: 无（未实现）；前置 P16-a 修复 `c357e5f`
- **Related Evaluation Reports**: `docs/evaluation/2026-08-26-biancheng-v025-eval.md`；设计 spec `docs/superpowers/specs/2026-08-26-p16b-relational-role-design.md`

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
- T4（2026-08-26 mock 实验）：M1（单候选吸收成立）、M5（翠翠的父亲 仅与顺顺共现 + judge 误判 → **错吸可复现，机制零拦截**）、M3/M4（多候选/null 时 judge 可正确）→ 根因锁定为 **judge 层无条件接受 resolves_to**（single-candidate 为放大因素）。
- T5（2026-08-26 设计评审）：候选 A（二次证据门槛）+ B（裸/限定结构区分）细化为 V0.2.6 spec；关键决策——父亲 因跨人物证据**正确地不建立 alias**（防 sink）；爸爸/爹爹 专属 → confirmed。
- T6（2026-08-26 v2 修订）：评审发现 v1 阻断性矛盾——`finalize 兜底确认`会绕过 ≥2 gate 且使 M5 错吸被确认；修订为**无自动晋升**（observation 永不确认）+ **跨 canonical 冲突 → blocked** + 触发条件收窄（老船夫 等 descriptive epithet 不进机制）。
- T7（2026-08-26 v3 修订）：评审发现 v2 残留漏洞——qualified 跨 chunk 重复误判仍可凑齐 ≥2 evidence（M16）；补齐 **anchor-mismatch 语义**：qualified + 锚点 ∉ 候选集 → 判定不可确认（不入 observation），M16 关闭。
- T8（2026-08-26 v4 修订）：评审发现 v3 残留漏洞——`anchor ∈ candidates` 不能证明 resolves_to C 正确（anchor 是关系主体非目标，M17 反例：翠翠的父亲 候选 [翠翠,顺顺] judge→顺顺）；新增 **target 对齐判据**（C == anchor 的 canonical 或 C 名 == 核词），qualified 单次 alias 需「对齐 + anchor 在场」双条件，M17 关闭。
- T9（2026-08-26 实现，TDD）：M1-M20 先红后绿；实现期三处修订——① 复合称谓**前缀**切分（岳云二老 若 岳云 非 known 回 bare）；② bare 触发收窄为**长辈称谓首字**（{父,爸,爹,母,妈,娘,婆,奶}，避免与 P17 冲突——晚辈称谓 大儿子/长子/次子 走 P17 路径）；③ anchor 文本在场含别名（_anchor_in_text，天保大老 的 anchor 别名「天保」在场视为在场）。全量：unit 207 / integration 15 全绿，P16-a/P17/RC2/RC3 零破坏。

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

## 13. Correct Approach（V0.2.6 候选 A+B 修订版 v4，评审中）

- **role 形态判定与核词提取**（确定性结构规则，非词表）：`qualified` = X的Y（anchor=X/核词=Y）或复合称谓（anchor=最长 known 名子串/核词=剩余）；`bare` = 其余。
- **target 对齐判据（v4 核心）**：qualified 的 judge 判定 C 必须满足 `C == anchor 的 canonical` 或 `C 名 == 核词`，否则 target-mismatch → 不可确认（M17：anchor 在场但 judge 选错 candidate 被拦截）。
- **anchor 在场为第二重条件**：对齐通过但 anchor ∉ 候选集 → 仍不可确认（anchor-mismatch）。
- **bare 证据准入（不变）**：judge 判 resolves_to → observation（chunk_id 去重）；≥2 独立证据 → confirmed → alias；<2 → 输出剔除；observation 永不自动晋升；跨 canonical 冲突 → blocked。
- **触发范围收窄**：bare 证据机制仅作用于 category=DESCRIPTIVE 且非 GENERIC；老船夫 等 descriptive epithet（PERSON）不进机制；COMPOSITE（天保大老/岳云二老）走 qualified 对齐路径。
- **合法 alias 保证**：爸爸/爹爹（≥2 证据）→ confirmed；翠翠的祖父（核词对齐+anchor 在场）→ 单次 alias；天保大老/岳云二老（anchor 对齐）→ 单次 alias；**父亲 跨人物 → 永不确认、不入图**（P16-b 目标）。
- 详见 spec v4 `docs/superpowers/specs/2026-08-26-p16b-relational-role-design.md`。

## 14. Invariants

- 不把 父亲/母亲/祖父 加入 generic 词表（P16 Do Not Reopen）。
- 不因 P16-b 未解决而判 P16-a/P17 失败。
- 不动 judge 契约 / merge bridge / Neo4j schema（需另立设计）。

## 15. Validation

- mock 实证（已完成）：M1 单候选吸收成立；M5 错吸可复现（无防御）；M3/M4 多候选/null 时 judge 可正确。
- ✅ **M1-M20（deterministic）全绿** → 全量回归（unit 207 / integration 15，P16-a/P17/RC2/RC3 零破坏）。关键用例：M5/M17（qualified 错吸 target-mismatch）、M11（无 finalize 绕过）、M12/M13（跨 canonical blocked）、M16（anchor 连续缺席不确认）、M18（对齐但 anchor 缺席不确认）、M19（anchor 无效 epithet 保护）、M20（复合 anchor 别名在场）。
- 真实评估验收指标（待下次）：role alias 吸收正误率（爸爸/爹爹→顺顺 建立；父亲 不建立）；翠翠的父亲 类跨人物称谓持续被拦截；顺顺 类 sink canonical 不再扩大错吸；LLM category 覆盖（长辈称谓裸词是否被标 DESCRIPTIVE——P06 follow-up）。

## 16. Trade-offs

- 语义正确的角色称谓吸收（爸爸→顺顺）是**期望行为**——不能一刀切禁止。
- **首次信息损失（无兜底补偿）**：bare role 首次 mention 输出剔除；全书仅 1 次证据 → 永久不入图（父亲 场景）。防错优先（v2 删除 v1 的 finalize 兜底——兜底正是 gate 的洞）。
- **触发依赖 LLM category（D5 同哲学）**：category=None/PERSON 的裸词不触发 → 保持现状（judge 吸收）；与 P17 D5 一致的 Known Limitation，不引入 classifier，走 P06 follow-up。
- **descriptive epithet 保护**：老船夫 类（category=PERSON）不进机制 → 现有 alias 路径零变化。
- 证据门槛依赖 judge 初次判定正确（observation 记录 judge 判定）；跨 canonical 冲突由 blocked 兜底——风险显著低于现状无条件接受。

## 17. Decision

- 确认为独立问题（P018），与 P16-a（题记污染）/P17（chunk 顺序碎片）边界清晰，**三问题独立回溯**。
- V0.2.6 采用候选 A+B（role alias 证据准入：裸/限定结构区分 + ≥2 独立证据 + 冲突信号 + 全书末兜底）；评审通过前不改代码。

## 18. Follow-up

- 设计评审通过（v3）→ 实现（resolver 新增 `_role_observations/_role_confirmed/_role_blocked` + `classify_role_mention` + anchor 在场判定 + evidence 分派；**无 novels.py 变更**）。
- 实现前先落 M1-M16 fixture（当前行为基线全红 → 实现 → 全绿）。
- 下次真实评估继续观察：顺顺 类 sink 吸收正误率、父亲 不建立 alias、翠翠的父亲 类持续拦截、LLM category 覆盖（父亲 是否被标 PERSON 而未触发——P06 follow-up）。
- Group / 关系角色建模：留待未来（P16-b 不引入）。

## 19. Current Limitation

- 无显式 relational-role 策略；依赖 judge null + unresolved 兜底，机制脆弱。
- 「父亲」正文歧义（≥3 人）未建模；同 chunk 共现时 judge 误判即错吸。

## 20. Do Not Reopen

- 再次出现 父亲→顺顺 类吸收：先查是否为语义正确吸收（aliases 可解释性核对）→ 再查跨人物错吸（翠翠的父亲 类）→ 属于 P018，**不要**回退 P16-a/-b。
- 不要用「把 父亲/爸爸/爹爹 加入 generic 词表」修复（破坏正向归并）。
- 不要把 P018 与 P16/P17 合并为单一策略。
