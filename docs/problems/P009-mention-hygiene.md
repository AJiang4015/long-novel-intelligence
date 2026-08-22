# P009 — Mention Hygiene：集合/泛指 mention 污染 Person 实体

- **Status**: 🔍 investigating（V0.2.4 已实现修复，真实《边城》验证待执行）
- **Severity**: **High**（已证明可造成整条 ER 数据污染）
- **Domain**: ER 算法 / extraction 契约
- **Tags**: er, hygiene, collective, generic, mention-category, pollution
- **First Seen**: V0.2 评估（傩送二老 垃圾 alias）
- **Last Verified**: V0.2.4 实现（128 unit / 15 integration）
- **Evidence Level**: HIGH（c4064416 污染可完整重现；确定性链路已证实）
- **Decision Type**: EXPERIMENT_RESULT（污染链重现）+ DESIGN_DECISION（V0.2.4 分类方案）
- **Related Problems**: P08（false merge 被 P09 放大）；P06（judge 单候选吸收）
- **Related Commits**: V0.2.4 系列 `bac35ed`/`cc5bb4b`/`fed0fff`/`22c22bb`/`11ad2e4`
- **Related Evaluation Reports**: 无独立报告（c4064416 观察 + 确定性 mock 实验）

## 1. Context

《边城》c4064416（V0.2.3 全管线：extract → resolve → canonical merge → Neo4j）出现严重过度合并：集合/泛指 mention 被当作 Person，污染整条 ER 链。

## 2. Symptom

Neo4j 中 `两个儿子` Person 节点：
```
canonical = "两个儿子"
aliases = ["天保","傩送","二老","傩送二老","岳云","大老","天保大人","天保大老",
           "哥哥","岳云二老","老二","弟弟","死去的人","年青人","顺顺大儿子","青年人"]
mention_count = 19, chapters = 17
```
同一实体的 16 个称谓（含多个不同人物）全部并入一个集合 canonical。

## 3. Impact

- 整条 ER 数据污染：天保/傩送/大老/二老 全部消失，合并为一个伪 Person。
- 关系（顺顺→两个儿子 family w=13）错误合并。
- 搜索任意相关名都命中 `两个儿子`。

## 4. Trigger

- Person aliases 出现「两个儿子」「年青人」等集合/泛指词。
- canonical 列表出现明显非专名词条。
- 同一 Person 的 mention_count 异常高（跨 17 章）。
- 大量错误合并（先怀疑 P09 再 P08 再 P06）。

## 5. Timeline（完整 forensic 链）

- T1（V0.2 评估）：「傩送二老」被 ER 吸收为 alias / 独立 canonical——垃圾 alias 首次观察（P09 萌芽）。
- T2（V0.2.3 真实评估 c4064416）：
  - chunk5 原文「他就有了八只船，一个妻子，**两个儿子**了」（集合用法）——extract LLM 把「两个儿子」输出为 **Person**。
  - `两个儿子` 在 chunk5 注册为 **canonical**（first_seen=5）。
  - chunk6 原文「作父亲的当**两个儿子**很小时…他把长子取名**天保**，次子取名**傩送**…诨名为**岳云**」——同 chunk 提取出 大儿子/天保/傩送/岳云，其候选**全部只有 `['两个儿子']`**（deterministic 实验证实：diag_chunk6_cands.txt）。
  - alias judge 面对唯一候选 → 天保→两个儿子、傩送→两个儿子、岳云→两个儿子、大儿子→两个儿子（**单候选吸收**）。
  - `两个儿子._index` 膨胀（含 天保/傩送/岳云）→ 后续任何含这些词的 chunk，`_text_mentions` 子串命中 `两个儿子`。
  - chunk10 `天保大人` 候选 [大老,两个儿子,二老] → 3 pair；chunk11 `天保大老` 候选 [大老,两个儿子,天保大人,二老] → 6 pair。
  - merge judge 全判 true → merge_map `{大老:二老, 二老:两个儿子, 天保大人:二老}` → 全部并入 `两个儿子`。
  - 后续章节：哥哥/弟弟/年青人/死去的人/顺顺大儿子/老二 经同 chunk 共现 alias judge 吸入。
  - 最终 16 aliases 污染（diag_two_sons.txt 实证）。
- T3（V0.2.4 诊断）：确认根因链 = extraction 集合→Person → alias judge 单候选吸收 → _index 膨胀 → text 扩散 → merge 桥接风暴。
- T4（V0.2.4 设计）：MentionCategory 六类 + resolver 决策表 + hygiene.py 范围锁死。
- T5（V0.2.4 实现）：`bac35ed`(Enum) → `cc5bb4b`(hygiene.py) → `fed0fff`(resolver) → `22c22bb`(extract prompt) → `11ad2e4`(stats)。128 unit / 15 integration 通过。
- T6（待执行）：真实《边城》评估验证 `两个儿子` 不再出现。

## 6. Initial Hypothesis

- 「垃圾别名是 judge 吸收问题」→ 后来发现**上游是 extraction 把集合当 Person**。
- 「judge 契约需要 drop 选项」→ V0.2.4 改为**分类 + 过滤**，不依赖 judge drop。

## 7. Investigation Path

```text
Step 1  查 canonical_aliases 中可疑项（两个儿子）
Step 2  回溯该 chunk 的 extract 输出（诊断日志 / 重放）
Step 3  确认 canonical 注册 chunk（first_seen）
Step 4  确认 alias judge 单候选吸收（deterministic 重放）
Step 5  确认 merge_evidence / merge judge 链（桥接风暴）
Step 6  对照 V0.2.2（765a7a13）：无两个儿子，天保大人/天保大老/岳云二老 正常消歧 → 证明污染由 V0.2.3 merge 链 + 集合 canonical 引入
```

## 8. Experiments

### Experiment E1（原文上下文）
- Environment: 全书 chunk 文本
- Input: 「两个儿子」关键词
- Hypothesis: 是否为集合用法
- Action: 位置扫描（.tmp/diag_two_sons_ctx.txt）
- Result: 全书仅 2 处，均为集合用法（「一个妻子，两个儿子了」「当两个儿子很小时」）
- Conclusion: extract 把集合 mention 当 Person 是污染起点

### Experiment E2（chunk6 候选确定性）
- Environment: resolver + mock judge（不调真实 LLM）
- Input: chunk5 注册两个儿子；chunk6 提取 两个儿子/大儿子/天保/傩送/岳云
- Hypothesis: 天保 等的候选是什么
- Action: resolve + 记录 pending candidates（.tmp/diag_chunk6_cands.txt）
- Result: 大儿子/天保/傩送/岳云 候选全部 = `['两个儿子']`
- Conclusion: 单候选吸收场景确定性成立

### Experiment E3（桥接风暴确定性）
- Environment: resolver + partial alias judge + merge judge 全 true
- Input: chunk5-11 序列
- Hypothesis: merge pair 如何产生
- Action: decide_merges（.tmp/diag_snowball3.txt）
- Result: `天保大老` 候选 [大老,两个儿子,天保大人,二老] → 6 pair；merge_map `{大老:二老, 二老:两个儿子, 天保大人:二老}`
- Conclusion: bridge 全量 pair + merge judge 全 true → 虹吸链确定性成立

### Experiment E4（V0.2.4 修复后 mock）
- Environment: V0.2.4 代码（hygiene + category 决策）
- Input: 同一 chunk5/6 场景
- Hypothesis: 两个儿子 不再注册
- Action: test_hygiene.py `test_collective_never_registered`
- Result: PASS（两个儿子 不进 known/_index/canonical_aliases）
- Conclusion: 修复有效（mock 层）

## 9. Evidence

- **database evidence**: c4064416 `两个儿子` 节点（16 aliases, mc=19, 17 章）；765a7a13 无此节点且 天保大人→大儿子/天保大老→大老/岳云二老→傩送 正常。
- **code evidence**: `hygiene.py`（hard rules）、`resolver.py`（category 决策表）、`schemas/llm.py`（MentionCategory）。
- **test evidence**: `test_hygiene.py` 39 项（含 collective 硬过滤/GENERIC 决策/不污染状态）。
- **experiment evidence**: E1-E4（.tmp 临时文件）。

## 10. Root Cause

完整污染链（每条均已证据确认）：

```
Extraction: 集合/泛指 mention（两个儿子）被输出为 Person
→ chunk5 注册为 canonical（first_seen=5）
→ chunk6 alias judge 单候选吸收（天保/傩送/岳云/大儿子 候选只有 [两个儿子]）
→ _index 膨胀（含天保/傩送/岳云）
→ text co-occurrence 子串扩散（任何含这些词的 chunk 命中两个儿子）
→ canonical merge bridge 全量 pair（天保大老/天保大人 → 6 pair）
→ merge judge 全判 true → 16 aliases 虹吸
```

## 11. Ruled-out Causes

- ~~judge 非确定性是主因~~：污染链可确定性重现（E2/E3），judge 只是执行错误输入下的合并。
- ~~canonical merge bridge 规则是主因~~：bridge 规则本身合理，问题在上游集合 canonical 进入候选。
- ~~judge 契约缺 drop 选项~~：V0.2.4 证明分类 + 过滤可解决，无需 judge drop。

## 12. Failed Approaches

- 让 ER 忠实吸收提取层输出（污染起点，已证伪）。
- 期望「增加 judge drop 选项」单独解决（方向对但依赖 judge 判别力，V0.2.4 改为确定性过滤优先）。

## 13. Correct Approach（V0.2.4 已实现）

- `MentionCategory` Enum：PERSON/GENERIC/COLLECTIVE/DESCRIPTIVE/COMPOSITE/INVALID（`schemas/llm.py`）。
- `hygiene.py` deterministic hard rules：**仅高置信 COLLECTIVE/INVALID 直接过滤**（量词模式/空/纯数字/超长）。
- resolver 决策表：
  - GENERIC：不建 canonical；有候选进 judge（通过→alias，null→丢弃）；无候选丢弃。
  - DESCRIPTIVE/COMPOSITE：不简单全量过滤；有候选进 judge；无候选允许注册 canonical（不静默丢人物）。
  - COLLECTIVE/INVALID：硬过滤，永不注册、不进 known/_index/canonical_aliases/merge_evidence。
  - PERSON / category=None：正常（None 走 legacy PERSON fallback，向后兼容）。
- extract prompt 输出 category（可选字段，向后兼容）。
- `_recall` 三层排除硬过滤 canonical（GENERIC 候选必须来自有效 canonical index，不吸收污染 canonical）。
- job stats `mention_hygiene`（collective_filtered/generic_filtered/descriptive_resolved/composite_resolved/invalid_filtered）。

## 14. Invariants

- COLLECTIVE/INVALID 永不成为 Person canonical。
- GENERIC 永不成为 canonical，但可作 alias mention 消歧。
- 被过滤 mention 不得进入 known/_index/canonical_aliases/merge_evidence。
- hard rules 只负责 COLLECTIVE/INVALID；GENERIC/DESCRIPTIVE/COMPOSITE 不得扩大为硬过滤。
- category=None → legacy PERSON fallback（不表示 LLM 判 PERSON）。

## 15. Validation

- 128 unit / 15 integration 全部通过（V0.2.4）。
- test_hygiene.py 锁死：两个儿子/兄弟二人 hard filter；弟弟/妇人/年青人 GENERIC 不过滤；岳云二老/天保大老/翠翠的祖父 不误伤。
- **真实《边城》评估待执行**（验证 `两个儿子` 不再出现、false merge 下降）——unverified。

## 16. Trade-offs

- COLLECTIVE 作 relation endpoint 时关系被丢弃（如 顺顺→两个儿子 family 边）——可接受（数据完整性优先，正确拆分留待 Group 模型）。
- DESCRIPTIVE/COMPOSITE 无候选时注册 canonical 是保守兜底——可能引入少量非专名 canonical，但避免丢人物。
- GENERIC 丢弃丢关系（哥哥→弟弟 等）——可接受。

## 17. Decision

- V0.2.4 采用「确定性 hard rules（COLLECTIVE/INVALID）+ LLM category（其余）+ resolver 决策表」方案。
- **不引入 Group 模型**（V0.2.4 只过滤，Group 留待未来）。
- **不修改 canonical merge bridge 规则**（先验证 hygiene 效果；bridge 限制为后续独立任务）。
- 不引入额外 LLM hygiene 调用（category 作为 extraction 契约一部分，零额外成本）。

## 18. Follow-up

- 真实《边城》评估：验证 false merge 显著下降、`两个儿子` 不出现。
- 视结果决定 merge bridge 候选限制（暂缓项）。
- 未来可评估 Group/Collective Entity 模型（V0.2.5+）。

## 19. Current Limitation

- LLM category 判定非确定（P06 域）——规则兜底覆盖 COLLECTIVE/INVALID，但 GENERIC/DESCRIPTIVE/COMPOSITE 依赖 LLM 分类，可能漏判。
- 真实《边城》验证未执行（unverified）。
- 旧库 c4064416 的 `两个儿子` 节点不迁移（范围外）。

## 20. Do Not Reopen

- 再次出现集合/泛指 canonical：先查 mention category（extract 输出）→ `hygiene.py` 规则 → resolver 决策，**不要**直接改 merge bridge。
- 不要重复「让 ER 忠实吸收提取输出」的旧做法。
- 不要因 DESCRIPTIVE/COMPOSITE 无候选注册而误判为 bug——那是防丢人物的有意兜底。
- 只有真实评估确认 false merge 未下降时，才重新评估（先查 category 覆盖率，再查 bridge 规则）。
