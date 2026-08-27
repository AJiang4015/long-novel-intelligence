# P017 — DESCRIPTIVE First-Seen Canonical Fragmentation：描述性称谓无候选直接建 canonical

- **Status**: 🔍 investigating（V0.2.5-b 已实现并验证 **PARTIAL**：B1 机制生效（unresolved 10 次），ch5b 一族未收敛系 D5 category 缺口；B2 后续）
- **Severity**: High（一族 6 碎片；45/61 节点 mc=1 单章）
- **Domain**: ER 算法 / canonical 注册策略
- **Tags**: er, descriptive, canonical-registration, first-seen, order-sensitivity, fragmentation
- **First Seen**: V0.2.4 真实《边城》评估（job `634f7f96`，novel `5c311fb3`）
- **Last Verified**: 2026-08-26 真实评估（job `1b7b7c1b`，novel `0ef3bd31`）
- **Evidence Level**: HIGH（ch5b 同 chunk 共现 + 碎片清单为确定性事实）；MEDIUM（judge 反序下是否合并依赖模型）
- **Decision Type**: EXPERIMENT_RESULT（真实评估观察）+ DESIGN_DECISION（V0.2.5-b：unresolved 不注册）
- **Related Problems**: P08（first-seen locking 机制）；P10（顺序敏感家族）；P06（judge 判定方差）；P16（共用注册缝，策略独立）；P09（trade-off 被 D2 有意取代）
- **Related Commits**: V0.2.5-b 实现 `c357e5f`（feat）/`27c8a2c`（test）
- **Related Evaluation Reports**: `docs/evaluation/2026-08-26-biancheng-v025-eval.md`；前置证据 job `634f7f96`（证据见本记录 §8/§9）

## 1. Context

《边城》ch5 第 5b chunk（[3600,4609)）单段内同时出现 大儿子/长子/次子/第二个儿子/天保/傩送/顺顺（偏移 3820–4532）。resolver 在 chunk 处理中途对「无候选的 DESCRIPTIVE」立即注册 canonical（`resolver.py:227-234`），先处理者绕过 judge → 一族碎片。

## 2. Symptom

- `大儿子` canonical（aliases=[], mc=1, ch=[5]）与 `天保` 分裂。
- ch5 一族 6 碎片：大儿子/长子/次子/第二个儿子（+天保/傩送 canonical）。
- 全书 61 Person 中 45 个 mc=1 且单章；团总儿子模样的青年/宋家堡子里新嫁娘/牵羊的孩子/卖皮纸的过渡人/代理看船的/老朋友/老熟人 等瞬时描述成为 canonical。

## 3. Impact

- 图谱碎片化：同一实体多节点，关系失真（天保/大老/大儿子/长子 各自为政）。
- 下游 merge 无法补救：无桥接 mention（大儿子 无桥）→ merge_evidence 无 pair；本次 merge judge 整体失败（109，INCONCLUSIVE）。
- 节点噪音：45/61 单章节点稀释图谱质量。

## 4. Trigger

- DESCRIPTIVE/COMPOSITE 首现 chunk 内无候选（先行 canonical 未建立）。
- 同一段落内描述性称谓与真名同现（「他把长子取名天保」）。
- 提取输出顺序变化导致谁先注册不确定（顺序敏感）。

## 5. Timeline

- T1（V0.2.4 评估 634f7f96）：大儿子/长子/次子/第二个儿子 独立 canonical；顺顺 被 P16 吸收。
- T2（2026-08-26 只读复核）：ch5b 偏移确认全族同 chunk；45/61 统计。
- T3（2026-08-26）：V0.2.5-b 设计锁定（含修订：unresolved 不注册；spec `2026-08-26-v025b-descriptive-policy-design.md`）。
- T4（2026-08-26 实现）：-b 落地（deferred + chunk 末重召回 + 单次 batch judge + unresolved 四路 + T-b1..T-b14）；unit 188 / integration 15 全绿。
- T5（2026-08-26 真实评估 1b7b7c1b）：`descriptive_unresolved=9` / `composite_unresolved=1`（**B1 机制真实生效**）；ch5b 一族仍 6 canonical（长子/次子/第二个儿子/大儿子 因 category≠DESCRIPTIVE 绕过 B1 → **D5 实证**）；P17 = **PARTIAL**。

## 6. Initial Hypothesis

「大儿子 无候选直接建 canonical，与 天保 形成两个 Person」——**成立**，且规模大于预期（全族 6 碎片）。

## 7. Investigation Path

```text
Step 1  EPUB 关键词章节分布（大儿子/长子/次子/天保/傩送）
Step 2  ch5 切块偏移 → 确认全族同 chunk（chunk B=[3600,4609)）
Step 3  Neo4j：mc=1 且单章节点清单（45 个）→ 分类 stable vs transient
Step 4  代码：_resolve_name 无候选分支 → _register（resolver.py:227-234）
Step 5  重放（mock 双序）→ 确认顺序敏感（实现后做 M1/M2）
```

## 8. Experiments

### E1（ch5b 偏移探针，2026-08-26）
- Input: ch5 全文 + chunk_size=4000/overlap=400
- Result: 两个小孩子@4063、顺顺@3820、大儿子@4439、第二个儿子@4458、长子@4477、天保@4481/4491、次子@4484、傩送@4488/4532——全部在 chunk B
- Conclusion: 碎片是**同 chunk 首现顺序竞态**，不是 zero-overlap 召回失败（P08 区分）

### E2（Neo4j 碎片清单，novel 5c311fb3）
- Result: 45/61 节点 mc=1 单章；ch5 有 6 个单章节点；ch9 有 团总儿子模样的青年/宋家堡子里新嫁娘/牵羊的孩子/卖皮纸的过渡人/第二个商人/卖纸人；ch11 有 18 个（说唱/典故人物）
- Conclusion: 描述性/瞬时 mention 的 canonical 化是主要噪音来源

### E3（代码路径核对）
- Result: `_resolve_name` 无候选分支：GENERIC 丢弃；PERSON/DESCRIPTIVE/COMPOSITE/None → `_register`
- Conclusion: DESCRIPTIVE/COMPOSITE 无候选时无任何延迟/重判机制

## 9. Evidence

- **database evidence**: novel `5c311fb3`：大儿子（[5]，无 aliases）、长子/次子/第二个儿子（[5]）、团总儿子模样的青年（[9]）等 45 个 mc=1 单章节点。
- **text evidence**: ch5 末段「作父亲的当两个儿子很小时，就明白大儿子一切与自己相似…他把长子取名天保，次子取名傩送」。
- **code evidence**: `resolver.py`（无候选注册分支、先处理者绕过 judge、first-seen locking）。
- **evaluation evidence**: job `634f7f96` 统计。

## 10. Root Cause

**DESCRIPTIVE/COMPOSITE（甚至 PERSON）无候选时在 chunk 处理中途立即注册 canonical，早于看到完整 chunk**。canonical 创建存在 chunk 内顺序竞态（P10 家族在 canonical 注册层复发）：先处理者绕过 judge 锁成 canonical，后处理者才拿到候选；first-seen locking（P08）使碎片永久化，且无桥接 mention 时 merge 无法补救。

## 11. Ruled-out Causes

- ~~「大儿子↔天保 是 zero-overlap 召回失败（P08）」~~：两者同 chunk 共现（ch5b 偏移实证），是注册顺序问题。
- ~~「judge 判定质量是主因」~~：先处理者根本没进 judge；judge 只是执行了「候选只有先注册者」时的判定。
- ~~「把 大儿子/长子/次子 加入词表」~~：它们是合法角色称谓，正确归宿是 alias 而非过滤；词表方案不解决顺序竞态。
- ~~「DESCRIPTIVE 全部 hard filter」~~：会摧毁 翠翠的祖父/天保大老/岳云二老 的合法 alias 路径（有候选路径完全正常）。

## 12. Failed Approaches

- 现行「DESCRIPTIVE/COMPOSITE 无候选 → 注册 canonical（不静默丢人物）」兜底（V0.2.4，P009 trade-off）——**被 V0.2.5-b D2 有意取代**：改为 unresolved 不注册（消除碎片优先，代价是单次描述性称谓可能不进图）。
- 期望 merge bridge 兜底：无桥接 mention 时不可达（本次实证：大儿子 无桥；merge 也因 LLM 失败 INCONCLUSIVE）。

## 13. Correct Approach（V0.2.5-b，已锁定）

- **B1 chunk 内 deferred**：DESCRIPTIVE/COMPOSITE 无候选 → 不进 known/_index，收集到 chunk 级 deferred。
- **chunk 末重召回**：本 chunk 新 canonical 入 _index 后对 deferred 重跑 `_recall`。
- **单次 batch judge（D3）**：deferred 重召回 candidate pairs 与处理期 pending **合并为同一次 judge 调用**（零额外 LLM 请求），`_apply_judge` 统一应用。
- **unresolved 语义（D2）**：无候选 / judge null / judge 缺失 / judge 异常 四路 → 不注册、不进 known/_index/aliases/merge_evidence、输出剔除、端点关系丢弃、计数。
- **judge 异常（D4）**：deferred 永不 canonicalize；PERSON/None → 兜底注册（既有 fail-safe）；GENERIC → 丢弃（与 RC3 对齐，修复既有 exception 路径洞）。
- **Known Limitation（D5）**：category=None → legacy PERSON fallback → B1 不生效（P06 follow-up；不引入 classifier）。
- 详见 spec `docs/superpowers/specs/2026-08-26-v025b-descriptive-policy-design.md`。

## 14. Invariants

- 翠翠的祖父 / 天保大老 / 岳云二老（有候选）alias 路径零变化；GENERIC/硬过滤/merge bridge/judge 契约零变化；PERSON 无候选立即注册不变。
- judge 每 chunk 至多一次（成本不变）；跨 chunk deferred（B2）本轮不实现。
- 不把 DESCRIPTIVE 全部 hard filter；不引入 classifier；不新增词表。

## 15. Validation

- ✅ T-b1..T-b14（deterministic，双 extraction 顺序断言顺序无关）全绿 → 修订 `test_hygiene.py:176` → 全量回归（unit 188 / integration 15）。
- ✅ 真实评估（job 1b7b7c1b）：B1 机制生效（descriptive_unresolved=9 / composite_unresolved=1）；一族最终 天保(7)/傩送(2)/大儿子(2)/长子(1)/次子(1)/第二个儿子(1) = 6 canonical——**未达 T-b3 的 {天保,傩送}**。
- ⚠️ **归因**：不是机制失败（10 次 unresolved 实证 + T-b 全绿）；是 **D5 Known Limitation**——一族 4 名 extraction category 非 DESCRIPTIVE（None→PERSON fallback 或 LLM 标 PERSON）→ 绕过 B1 立即注册。**记录为 P017 Known Limitation / P06 follow-up，不改代码。**
- 另含 P08/P06 域：傩送↔二老 分裂（提取变异性）、岳云(ch5) 独立 canonical（与 -b 无关）。

## 16. Trade-offs

- unresolved 不注册：消除碎片优先，代价是「仅以描述性称谓出现的真实人物」可能不进图（罕见；PERSON 仍保底）。
- judge 依赖（D5）：LLM 未给 category 时 B1 不生效——已知缺口，接受并追踪 P06。
- 异常路径 GENERIC 丢弃：与 RC3 语义一致，但改变既有 exception 路径行为（修复洞，非回归）。

## 17. Decision

- V0.2.5-b 采用 B1（chunk 内 deferred + 单次 batch judge + unresolved 不注册）（评审 2026-08-26 锁定/修订）。
- B2（跨 chunk deferred）为后续独立能力；D5 缺口正式列入 Known Limitation / P06 follow-up。

## 18. Follow-up

- ✅ -b 实现 + 真实评估 PARTIAL（见 §15）。
- **D5 / P06 follow-up**：extraction category 覆盖率与质量（category=None 时 B1 不生效；本次 39 个 mc=1 中规则推断 24 个潜在非专名碎片候选——真实 category 分布需重放或链路日志确认）。
- **B2**（跨 chunk/跨章 deferred）独立设计（真实评估一族 4 名绕过 B1 亦与 B1 的 chunk 内范围有关）。
- RC2 覆盖面缺口（两个小孩子/两个年青人）→ P09 follow-up。

## 19. Current Limitation

- B1 依赖 LLM category（DESCRIPTIVE/COMPOSITE）触发；category=None 的描述性 mention 仍按 PERSON 立即注册（D5）。
- judge null 时 deferred 虽不注册，但若该描述性称谓是唯一出现形式，实体不进图（接受的取舍）。
- 跨章首现（大儿子 在 ch5、真名在更早/更晚章节且不同 chunk）不在 B1 覆盖——B2 后续。

## 20. Do Not Reopen

- 再次出现描述性碎片：先重放（mock 双序）确认是否顺序敏感 → 检查 category 覆盖率（D5 缺口）→ 再查 judge 判定（P06）。
- 不要用「DESCRIPTIVE 全部 hard filter」或「把 大儿子/长子/次子 加入词表」修复。
- 不要把 P17 与 P16 合并为单一词表/单一策略；不要把「无法确认不注册」当成回归（D2 是有意取代 P009 兜底）。
