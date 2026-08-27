# P016 — Metadata/Epigraph Context Pollution：非正文文本污染 canonical 首现

- **Status**: ✅ resolved/verified（P16-a 已实现并真实评估验证 **PASS**；P16-b 单独立项见 P018）
- **Severity**: High（可整族吞并正文实体：顺顺 组消失）
- **Domain**: ER 算法 / 章节上下文
- **Tags**: er, context, section-type, epigraph, metadata, canonical-sink, pollution
- **First Seen**: V0.2.4 真实《边城》评估（job `634f7f96`，novel `5c311fb3`）
- **Last Verified**: 2026-08-26 真实评估（job `1b7b7c1b`，novel `0ef3bd31`）
- **Evidence Level**: HIGH（结构事实：ch2 题记含 父亲、父亲 chapters 含 2、顺顺 无节点、沈从文/兆和 纯非正文）；MEDIUM（吸收顺序依赖模型与单次运行，ch4 等 chunk 抽取失败引入噪声）
- **Decision Type**: EXPERIMENT_RESULT（真实评估观察）+ DESIGN_DECISION（V0.2.5-a 方案）
- **Related Problems**: P08（级联破坏 merge 桥接）；P09（RC3 词表边界：祖父/父亲/母亲 不入表）；P06（judge 吸收放大）；P17（共用注册缝，策略独立）；P18（P16-b：正文 relational-role sink，单独立项）
- **Related Commits**: V0.2.5-a 实现 `c357e5f`（feat）/`27c8a2c`（test）/`cda30b1`（docs）
- **Related Evaluation Reports**: `docs/evaluation/2026-08-26-biancheng-v025-eval.md`；前置证据 job `634f7f96`（无独立报告文件，证据见本记录 §8/§9）

## 1. Context

《边城》EPUB：ch1 版权 / ch2 题记 / ch3 新题记 / ch4–24 正文 / ch25 推广。resolver 无 section/context awareness，非正文与正文使用同一 canonical 注册策略，亲属/角色称谓词在题记语境被注册为 canonical，随后充当正文实体的 canonical sink。

## 2. Symptom

- `父亲` canonical（mc=13，chapters=[2,5,6,8,11,12,13,14,16,19,20,22,23]）aliases=[顺顺,顺顺大哥,顺顺船总,翠翠的父亲,船总顺顺,中年人,爹爹]；`MATCH Person name="顺顺"` 无记录。
- `沈从文`（mc=3, ch=[1,2,3]）、`兆和`（mc=1, ch=[3]）为纯非正文 Person 节点。
- 题记「我的祖父，父亲，以及兄弟，全列身军籍」建成 `沈从文-[family]->祖父/父亲/母亲`、`沈从文-[love]->兆和` 边。

## 3. Impact

- 正文实体（顺顺）被吞并 → 节点消失、家族图整体错位（`父亲-[family]->天保/大老/傩送` ≈0.93 看似自洽实则混并 ≥3 人）。
- 作者/题记人物入图（沈从文/兆和）+ 题记派生边污染。
- 隐形污染：祖父/母亲 字符串正确但 first_seen/mc/chapters 被非正文污染，且引入可疑 alias（祖父→张横）。
- 级联：顺顺 被吞 → ch24「顺顺大儿子的死」桥接失效 → P08 merge 质量进一步退化。

## 4. Trigger

- canonical 的 chapters 含非正文章节（版权/题记/新题记/推广，如 ch1/2/3/25）。
- 正文高频实体的 canonical 名与题记亲属称谓重合（父亲/母亲/祖父）。
- 同一 canonical 的章节集远大于其原文出现章节（alias 扩散特征）。

## 5. Timeline

- T1（V0.2.3 stability 评估 3d782d98）：顺顺 自身为 canonical（mc=16）——同 EPUB 但模型不同（qwen3.7-max-preview），未观察到 父亲 吸收（模型相关）。
- T2（V0.2.4 评估 634f7f96，qwen3.7-plus-2026-05-26）：父亲 吸收 顺顺 组；沈从文/兆和 入图。
- T3（2026-08-26 只读复核）：EPUB 结构确认；Neo4j 非正文污染节点清单（5 个）；ch5b 同 chunk 证据（顺顺@3820 与「作父亲的」@~4430）。
- T4（2026-08-26）：V0.2.5-a 设计锁定（spec `2026-08-26-v025a-context-er-design.md`）。
- T5（2026-08-26 实现）：V0.2.5-a 落地（sections.py + Chapter/Chunk.section_type + provisional/promotion/finalize + T-a1..T-a14）；unit 174 / integration 15 全绿。
- T6（2026-08-26 真实评估 1b7b7c1b）：非正文 canonical=0（沈从文/兆和 消失）；provisional 3→3 dropped；祖父/母亲 无题记章节；`父亲` canonical 不存在 → **PASS**。

## 6. Initial Hypothesis

「父亲 在题记（ch2）首次被提取并注册 canonical，之后正文 顺顺 被吸收」——**结构上成立**（ch2 含 父亲 且 父亲 chapters 含 2）。

## 7. Investigation Path

```text
Step 1  EPUB 章节结构探针（ch1-25 内容/首行/长度）→ 识别非正文章节
Step 2  关键词章节分布（父亲/祖父/母亲/兆和/顺顺/大儿子…）
Step 3  Neo4j：novel 5c311fb3 全部 Person 的 chapters/aliases → 章节集含 1/2/3/25 的 canonical
Step 4  Neo4j：涉事 canonical 的关系边（题记派生边 vs 正文边）
Step 5  ch 内偏移 → 确认 顺顺/父亲 同 chunk 共现（吸收现场）
Step 6  区分：非正文首现污染（P16）vs 正文内 relational-role sink（P16-b）
```

## 8. Experiments

### E1（EPUB 结构探针，2026-08-26）
- Input: `books/边城….epub` → read_epub
- Result: 25 章；ch1 版权(14)/ch2 题记(1670)/ch3 新题记(404)/ch4-24 正文/ch25 推广(105)；全部无 item title
- Conclusion: 非正文章节内容可识别；分类必须内容/位置启发式

### E2（Neo4j 只读查询，novel 5c311fb3）
- Query: `MATCH (p:Person) WHERE p.novel_id=$nid RETURN p.name, p.mention_count, p.chapters, p.aliases`
- Result: 61 Person；章节集含 1/2/3/25 共 5 个（沈从文/父亲/祖父/母亲/兆和）；沈从文-[love]->兆和、沈从文-[family]->祖父/父亲/母亲（0.95）
- Conclusion: 非正文污染范围精确可列

### E3（ch5b 偏移探针）
- Result: ch5 切块 B=[3600,4609)：顺顺@3820、父亲(作父亲的)@~4430、大儿子@4439、长子@4477、天保@4481/4491、傩送@4488/4532 同 chunk
- Conclusion: 顺顺→父亲 吸收在正文 chunk 内完成（sink 形成现场）

## 9. Evidence

- **database evidence**: novel `5c311fb3`：父亲（13 章/8 aliases）、沈从文（[1,2,3]）、兆和（[3]）、祖父（ch 含 2）、母亲（ch 含 3）；顺顺 无节点；题记派生边。
- **text evidence**: ch2 题记原文；ch4/5/16/24 正文「父亲」语境（翠翠的父/作父亲的/作渡船夫的父亲 ≥3 人）。
- **code evidence**: `resolver.py`（无候选注册分支、`_text_mentions` 子串候选、`_register`）；`chunker.py`（Chunk 无 section 字段）；`epub_reader.py`（无 section 分类）。
- **evaluation evidence**: job `634f7f96` 统计（用户提供，2026-08-26 复核）。

## 10. Root Cause

**resolver 无 section/context awareness**：`Chunk` 仅含 chapter_id/chapter_title，canonical 注册策略对 版权/题记/推广 与 正文 一视同仁。亲属/角色称谓（父亲/祖父/母亲/长子…）在非正文语境被注册为 canonical，经 `_text_mentions` 子串扩散成为正文实体的 canonical sink（顺顺→父亲 经 judge 吸收）。

## 11. Ruled-out Causes

- ~~「父亲/母亲/祖父 应加入 generic 词表」~~：正文真实人物（祖父=老船夫 核心人物），全局 GENERIC 化摧毁真实实体；是 context 问题不是 lexicon 问题。
- ~~「跳过前 N 章即可」~~：不同 EPUB 结构不同；ch3 新题记含真实专名 兆和，硬编码跳过会误伤。
- ~~「LLM category 足以区分」~~：兆和/沈从文 是 PERSON 仍污染；只有 BODY 确认能区分小说人物与题记人物。
- ~~「顺顺→父亲 只是 judge 质量问题（P06）」~~：judge 是执行者；结构性根因是非正文 canonical 先于正文注册并成为候选源。

## 12. Failed Approaches

- V0.2.4 前：让 ER 忠实吸收抽取输出（污染起点，P009 已证伪并修复）。
- RC3 词表边界：祖父/父亲/母亲 不入表是正确决策（P009），但不能解决 P16（需上下文而非词表）。

## 13. Correct Approach（V0.2.5-a，已锁定）

- SectionType（METADATA/EPIGRAPH/BODY/TRAILER）+ `sections.py` 确定性分类（内容/位置启发式，默认 BODY，禁止跳过 N 章）。
- `Chapter.section_type` → `Chunk.section_type`（overlap 不跨章 → chunk 永不混 section）。
- 注册门控：BODY 行为不变；非正文 GENERIC 丢弃/硬过滤不变、DESCRIPTIVE/COMPOSITE 永不注册、PERSON 恒 provisional。
- provisional 不入候选源（`confirmed`/`text_confirmed`/`_recall`），BODY 同名字出现（known-hit）晋升；`finalize()` flush 未确认 provisional（不入图+端点关系丢弃+计数）。
- 非正文 chunk 不参与 mc/chapters 统计；stats 扩展 `nonbody_person_provisional`/`nonbody_descriptive_dropped`/`nonbody_provisional_dropped`。
- 详见 spec `docs/superpowers/specs/2026-08-26-v025a-context-er-design.md`。

## 14. Invariants

- RC2/RC3 全部语义不变；PERSON 无候选立即注册不变。
- provisional 晋升前对候选层完全不可见（T-a14 锁死）。
- 非正文专名（兆和/沈从文）保留于抽取输出（不被 hygiene 误删），仅图级排除。
- 不把 父亲/母亲/祖父 加入 generic 词表；不做「跳过前 N 章」；不动 merge bridge/judge 契约/并发超时。

## 15. Validation

- ✅ T-a1..T-a14（deterministic）全绿 → 全量回归（unit 174 / integration 15）。
- ✅ 真实评估（job 1b7b7c1b）：非正文 canonical=0（沈从文/兆和 消失）；provisional 3→3 dropped；祖父 mc=14 chapters 无 ch2/3；母亲 mc=7 无 ch3；`父亲` canonical 不存在 → **P16-a = PASS**。
- ⚠️ **`顺顺→父亲` 在 V0.2.5-a 后仍在正文内发生（ch5b「作父亲的」）→ 不判 P16-a 失败**：属已切出的 **P16-b（正文 relational-role canonical sink，P018 单独立项）**；本次评估为 P16-b 首次干净观察（不再与题记污染混杂）。

## 16. Trade-offs

- 非正文 DESCRIPTIVE/COMPOSITE 丢弃 → 题记语境描述性称谓不产生节点（正确）。
- provisional flush 丢弃 → 极少数「只在序言出现的真实专名」可能不入图（兆和 属此；接受，因非小说人物；可配置保留为后续）。
- 不解决 P16-b（正文内 父亲/顺顺 吸收）→ 残留风险显式记录，另行诊断。

## 17. Decision

- V0.2.5-a 采用「section 分类 + 注册门控 + provisional/promotion/flush」方案（评审 2026-08-26 锁定）。
- 兆和/沈从文 终态：无正文确认 → 不入图（D1）。
- 不引入 LLM section 分类器；确定性规则优先。

## 18. Follow-up

- ✅ -a 实现 + 真实评估 PASS（见 §15）。
- **P16-b**（正文 relational-role canonical sink）：**已单独立项 → P018**（真实评估首次干净观察：顺顺 aliases 8 项全可解释、翠翠的父亲 未错吸；机制脆弱待设计）。
- RC2 覆盖面缺口（两个小孩子/两个年青人 未命中 COLLECTIVE 模式）→ P09 follow-up（不在 P16 范围）。
- 链路可观测性（下次评估前为 extract/judge 增加日志或中间产物落盘，用于直接观测 canonical 决策）→ 代码改动，另立项。

## 19. Current Limitation

- 非正文分类依赖内容标记启发式（换 EPUB 需重新评估标记）。
- provisional 晋升依赖 BODY 同名字出现或 judge 合并——若正文以不同称谓指代题记同名实体，可能残留少量错并（P06 域）。
- P16-b 未解决：正文内「父亲」歧义仍可能造成 顺顺→父亲 类吸收。

## 20. Do Not Reopen

- 再次出现非正文污染 canonical：先查「章节集含 1/2/3/25 的 canonical 清单」→ 确认 section 分类 → 检查 provisional 是否进入候选源（T-a14 回归）。
- 不要用「把 父亲/母亲/祖父 加入 generic 词表」修复；不要用「跳过前 N 章」修复。
- 不要把 P16 与 P17 合并成单一词表/单一策略；不要把 P16-b（正文内 sink）归入 P16-a 验收。
