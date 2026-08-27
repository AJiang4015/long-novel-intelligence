# V0.2.5-a/b Real Evaluation Acceptance & Attribution

> **本报告是 V0.2.5-a/b 的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**
> 尤其注意：报告中「P17 = PARTIAL」与「P16-b 需单独立项」均指**已知限制/后续设计项**，不是本轮缺陷清单；未经新设计评审不得据此直接修改 resolver / hygiene / prompt / judge / merge bridge / Neo4j schema。

## 1. Environment Baseline

| 项 | 值 |
|---|---|
| job_id | `1b7b7c1b-5e95-4602-87d8-815f0db85ed6` |
| novel_id | `0ef3bd31-51dd-458a-9bf7-c88144fb3942` |
| 小说 | 《边城》(沈从文)，27 chunks |
| Git | HEAD=`83db5f7`（V0.2.4-b RC3 冻结点）；工作区含 **V0.2.5-a + V0.2.5-b 全部未提交实现** |
| 模型 | 以运行时刻 `.env` 为准（当前 `.env`=`qwen3.7-max-2026-06-08`；运行时刻值未记录，标注不确定） |
| chunk_size / overlap / concurrency | 4000 / 400 / **2** |
| Neo4j | novel-neo4j（5.26.x Community，独立实例） |
| 终态 | `completed_with_errors`；54 Person / 63 RELATES_TO |

**失败块（job API 精确值，7 个）**：chunk4/ch4 ReadTimeout、chunk8/ch7 ReadTimeout、chunk9/ch8 alias_resolution_failed、chunk10/ch9 ReadTimeout、chunk14/ch13a validation_error、chunk17/ch15 ReadTimeout、chunk23/ch21 ReadTimeout。

**stats**：`merge_candidate_pairs=155 / merged=0 / failed=155`（batch merge judge 再次整体失败 → merge **INCONCLUSIVE**，RC1/LLM 稳定性域）；`mention_hygiene = {collective_filtered:2, generic_filtered:8, descriptive_resolved:7, composite_resolved:6, invalid_filtered:0, nonbody_person_provisional:3, nonbody_descriptive_dropped:0, nonbody_provisional_dropped:3, descriptive_unresolved:9, composite_unresolved:1}`。

---

## 2. V0.2.5-a / P16-a：**PASS**

| 验收项 | 结果 | 证据 |
|---|---|---|
| 非正文 canonical | **0** | `沈从文` / `兆和` / `父亲` canonical 均不存在（Neo4j 确认） |
| provisional → promoted | **0** | 沈从文(ch1)+从文(ch2/3)+兆和(ch3) = 3 个 provisional，全部无正文确认 |
| provisional → dropped | **3** | `nonbody_person_provisional=3` / `nonbody_provisional_dropped=3` |
| 祖父 题记污染 | **无** | mc=14，chapters=[8,10,11,12,13,14,16,17,18,19,20,22,23,24]，无 ch2/3 |
| 母亲 题记污染 | **无** | mc=7，chapters=[5,10,11,14,16,24]，无 ch3 |
| metadata 污染正文 canonical | **NO** | 题记派生边（沈从文-family/love）消失；`nonbody_descriptive_dropped=0` |

**自洽性验证**：祖父 chapters 缺失的 ch4/7/9/13a/15/21 全部命中本次失败块（ch5/6 无祖父原文）——chapter 集与失败块完全吻合，证明「缺失 = 失败 chunk 或原文无」，而非题记污染。

**结论**：题记首现污染已彻底分离（first_seen / mention_count / chapters 均不含非正文）。

---

## 3. V0.2.5-b / P17：**PARTIAL**（机制真实生效；D5 category 缺口阻断一族收敛）

### 3.1 ch5b 链路追踪

1. **ch5b 是否成功处理**：ch5b = chunk6，不在 7 个失败块中 → extraction + resolve 均成功。
2. **一族同 chunk 事实**：大儿子@4439 / 第二个儿子@4458 / 长子@4477 / 天保@4481 / 次子@4484 / 傩送@4488 / 顺顺@3820 / 岳云@4566 / 两个年青人@3892——全部在 chunk6 文本 [3600,4609)。
3. **deferred 机制是否执行**：**是，全书生效**——`descriptive_unresolved=9` + `composite_unresolved=1` 证明 deferred→重召回→judge→unresolved 链路在真实运行中被执行（机制未生效时这些计数恒为 0）。
4. **但 ch5b 一族未走 deferred**：长子/次子/第二个儿子 mc=1 各自 canonical ⇒ extraction category **不是 DESCRIPTIVE**（category=None→legacy PERSON 立即注册，或 LLM 标 PERSON）→ 绕过 B1。
5. **真实运行 extraction 顺序 / recall candidates / batch judge 输入输出**：**未持久化，无法从留存数据还原**（extraction 输出、pending、judge 结果均未落盘；唯一反推依据 = 最终 canonical 状态 + stats 计数）。**证据不足，需下次评估增加链路日志才能直接观测。**
6. **一族最终状态**：

| canonical | mc | aliases | 归因 |
|---|---|---|---|
| 天保 | 7 | [天保大老] | ch5b 注册（PERSON）→ 后续正确吸收 天保大老 |
| 傩送 | 2 | [] | ch5b 注册；之后章节 LLM 主要提取为「二老/傩送二老」→ **傩送↔二老 分裂（P08 域提取变异性）** |
| 大儿子 | 2 | [顺顺大儿子] | ch5b 注册（category 非 DESCRIPTIVE）；ch24「顺顺大儿子」judge→alias ✓（语义正确，canonical 名选 大儿子 而非 天保） |
| 长子 / 次子 / 第二个儿子 | 1 | [] | **D5 Known Limitation 实证**：category=None/PERSON → 绕过 B1 立即注册 |

### 3.2 失败原因归类

- ❌ **不是 deferred 机制失败**（机制有 10 次 unresolved 实证；T-b1~T-b14 mock 全绿）。
- ✅ **是 D5 category 覆盖缺口**：一族 4 个亲属描述名未获 DESCRIPTIVE 标注 → B1 不生效（P017 Known Limitation 正中央）。
- ✅ 另有 **P08/P06 域**：傩送↔二老 分裂、岳云(ch5) 独立 canonical（零共享字 + 提取变异性，与 -b 无关）。

**结论**：**P17 = PARTIAL**——B1 机制真实收敛了 9 个 DESCRIPTIVE + 1 个 COMPOSITE 无法确认 mention；ch5b 一族未达 T-b3 的 {天保, 傩送}，系 **D5 已知限制兑现**，非实现失败。

---

## 4. P16-b（正文 relational-role canonical sink）：独立问题确认

- **父亲→顺顺 吸收：存在**。顺顺 mc=14 aliases=[爸爸, 父亲, 顺顺大哥, 顺顺船总, 船总顺顺, 中年人, 爹爹, 船总]；`父亲` canonical 已不存在（P16-a 分离成功）。
- **吸收 chunk**：ch5b（「作父亲的当两个儿子很小时…」= 顺顺），顺顺 chapters 含 5 ✓，**语义正确**。
- **8 个 aliases 逐条可解释性**（EPUB 原文核对）：爸爸(ch5/6/14/22)=顺顺 ✓、爹爹(ch13/20)=顺顺 ✓、中年人(ch19)=船总顺顺 ✓、船总/顺顺大哥/顺顺船总/船总顺顺=顺顺称谓 ✓、父亲(ch5b)=顺顺 ✓——**全部可解释**。
- **错误吸收检查**：`翠翠的父亲`（ch16/24）= 翠翠之亡父 ≠ 顺顺 → **未进入顺顺 aliases**（aliases 无「翠翠的父亲」，顺顺 chapters 无 16）→ 本次**未发生跨人物错误吸收**；ch16 的「翠翠的父亲」应计入 `descriptive_unresolved=9`（候选含 翠翠/祖父 而无顺顺 → judge null → unresolved）或被 -b 兜住。
- **judge evidence**：无法还原（无日志）；父亲→顺顺 判定发生在 ch5b 单次 batch judge，输入候选含 顺顺（同 chunk 共现）。

**结论**：P16-b 机制确认独立存在（「父亲」作为 顺顺 角色词被正文内吸收，语义正确但 canonical 名脆弱）；**本次未观察到错误吸收**，但依赖 judge null + unresolved 兜底，**机制脆弱**（若 ch16/24 的「翠翠的父亲」judge 误判 → 错吸）。**需下一轮 P16-b 单独立项设计**（与 -a 题记污染已成功分离，本次为 P16-b 首次干净观察）。

---

## 5. P017 Known Limitation 统计（本轮不修，记入 P06 follow-up）

- **mc=1 canonical：39 个**（共 54）。
- 规则推断分类（**非真实 extraction category**——留存数据不含 category，需重放确认；None 与 PERSON 效果等价，都绕过 B1）：

| 类别 | 数量 | 示例 |
|---|---|---|
| 典故/说唱专名（非小说人物，PERSON-ish） | 9 | 梁红玉/牛皋/杨么/关夫子/张果老/李鸿章/洪秀全/尉迟公/铁拐李 |
| 职业/角色/泛指（GENERIC-ish） | 21 | 两个年青人/妇人/商人/兵营中人/副爷/卖肉的/大老板/大姐/二姐/三妹/母女二人/火夫/马夫/脚夫/伙计… |
| 亲属描述（DESCRIPTIVE-ish） | 3 | 长子/次子/第二个儿子 |
| 真实专名/未定 | 6 | 岳云（应 alias 傩送）/顺顺父子（COMPOSITE 语义）/毛伙/王团总/厘金局长/秃头陈四四 |

- **潜在非专名碎片候选（D5 缺口）**：**24 个**（亲属描述 3 + 角色/泛指 21，规则推断）。
- **category=None vs PERSON 真实分布**：**无法从留存数据区分**（需下次评估落盘 extraction category，或对 mc=1 清单重放）。
- **判定**：与 V0.2.5-b D5 一致——`category=None → legacy PERSON fallback → 立即 canonical`。**记录为 P017 Known Limitation / P06 follow-up，不是本轮 bug，不改代码。**

---

## 6. 失败块影响

| chunk/chapter | 错误 | 内容损失 | 对结论的影响 |
|---|---|---|---|
| chunk4/ch4 | ReadTimeout | 正文首章（翠翠身世、祖父×11、黄狗×7、父亲×4） | 翠翠/祖父 first_seen 后移；「翠翠的父亲」早期线索缺失 |
| chunk8/ch7 | ReadTimeout | 端阳节 翠翠/傩送 初遇（傩送×2） | 傩送-翠翠 共现缺失（傩送 mc=2 部分成因） |
| chunk9/ch8 | alias_resolution_failed | 全 chunk pending 走异常路径 → PERSON 兜底注册（碎片风险）；ch8 为 大老/二老/祖父 高频章 | 该章 alias 合并全部未发生；**不影响 -b 机制判断** |
| chunk10/ch9 | ReadTimeout | 祖父×19、黄狗×5 | 质量损失 |
| chunk14/ch13a | validation_error | 王团总@960 丢（ch13b 王团总@4200 幸存 → 王团总 mc=1 自洽） | 无关键结论依赖 |
| chunk17/ch15 | ReadTimeout | 祖父×3、王团总 | 质量损失 |
| chunk23/ch21 | ReadTimeout | 祖父×7、黄狗 | 质量损失 |

**关键判断**：27→20 chunk 有效，但结论不依赖失败 chunk 的正面证据——-a 验收依赖 ch1-3（题记章节**全部成功**）；-b 机制判断依赖 ch5b（chunk6 **成功**）；P16-b 依赖 ch5b/ch16（ch16 **成功**）。`merge 155 pairs 全 failed` → canonical merge **继续 INCONCLUSIVE**（RC1 域）。

---

## 7. 总体结论

| 项 | 结论 |
|---|---|
| P16-a | **PASS**——题记污染彻底分离（非正文 canonical=0、provisional 3→3 dropped、祖父/母亲 无题记章节） |
| P17 | **PARTIAL**——B1 机制真实生效（10 次 unresolved）；ch5b 一族未收敛系 **D5 category 缺口**（4/6 名绕过 deferred），非机制失败 |
| P16-b | **确认独立存在**——父亲→顺顺 正文内吸收（语义正确、8 aliases 全可解释、无跨人物错误吸收）；机制脆弱，**需单独立项设计** |
| P017 Known Limitation | 39 个 mc=1；潜在非专名碎片候选 **24**；category 分布需重放确认 → **记入 P06 follow-up，不修** |
| merge | INCONCLUSIVE（155 全 failed，LLM 稳定性域） |

**已确认的后续设计项（另立设计/Problem Record，不在本验证报告内实施）**：
1. **P16-b**：正文 relational-role canonical sink 策略（区分 角色称谓吸收 与 跨人物错吸；本次翠翠的父亲 靠 judge null + unresolved 兜住，机制脆弱）。
2. **P017 D5 / P06 follow-up**：extraction category 覆盖率与质量（category=None 时 B1 不生效；24 个潜在非专名碎片候选）。
3. **链路可观测性**（若需直接观测 ch5b：extraction 顺序 / category / recall / judge 输入输出）——下次评估前为 extract/judge 增加日志或中间产物落盘（代码改动，另立项）。
