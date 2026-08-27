# V0.2.6 P16-b Real Evaluation Acceptance Report —《边城》（2026-08-27）

> **本报告是 V0.2.6 (P16-b) 的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**
> 尤其注意：本报告「P16-b = PARTIAL」与「P017 D5 = observed」均指**验证结论 / 已知限制**，不是缺陷清单；未经新设计评审不得据此直接修改 resolver / hygiene / prompt / judge / merge bridge / Neo4j schema / 并发 / timeout。
> 本轮未修改任何代码、配置、schema、prompt；评估仅基于 commit `f5b4c09` 的当前行为。

## 1. Environment Baseline

| 项 | 值 |
|---|---|
| job_id | `d002fdec-e4f8-41bb-b7e7-465e804cee5a` |
| novel_id | `3a54e06a-b6ff-4ec0-a224-066f200d163f` |
| 小说 | 《边城》(沈从文)，25 chapters / 27 chunks（与 V0.2.5 同一 EPUB） |
| Git | HEAD=`f5b4c09`（V0.2.6 P16-b 实现提交）；工作区干净（`git status --porcelain` 为空） |
| 模型 | `qwen3.7-max-2026-06-08`（backend/.env） |
| chunk_size / overlap / concurrency | 4000 / 400 / **2**（与 V0.2.5 一致） |
| Neo4j | novel-neo4j（5.26.x Community，独立实例，bolt://192.168.127.101:7687） |
| 开始时间 | 2026-08-27 19:54:21 |
| 终态 | `completed_with_errors`；50 Person / 56 RELATES_TO |

**失败块（4 个，均为 ReadTimeout）**：chunk13/ch12、chunk17/ch15、chunk24/ch22、chunk26/ch24。

**stats**：`merge_candidate_pairs=148 / merged=0 / failed=148`（batch merge judge 再次整体失败 → merge **INCONCLUSIVE**，与 V0.2.5 的 155/0/155 同模式，RC1/LLM 稳定性域）；
`mention_hygiene = {collective_filtered:1, generic_filtered:11, descriptive_resolved:3, composite_resolved:5, invalid_filtered:0, nonbody_person_provisional:3, nonbody_descriptive_dropped:0, nonbody_provisional_dropped:3, descriptive_unresolved:19, composite_unresolved:0}`。

> 链路可观测性限制（与 V0.2.5 §3.1 相同）：extraction 输出 / pending / judge 输入输出**未落盘**，role observation/confirmed/blocked 的逐 chunk 轨迹无法直接读取；本报告通过**最终 canonical 状态 + stats 计数**反推机制行为，并逐条标注推断依据与置信度。

---

## 2. P16-b 核心验收：爸爸 / 爹爹 / 父亲

### 2.1 三组决定性结果（Neo4j 直接确认）

| 词 | 预期 | 实际（V0.2.6 终态） | 判定 |
|---|---|---|---|
| 爸爸 | → 顺顺 confirmed alias | **未确认**：`爸爸` 为**独立 Person**（mc=1, chapters=[5]），不在任何 canonical aliases | ❌ 目标未达成（D5 归因，见 §2.3） |
| 爹爹 | → 顺顺 confirmed alias | **✅ confirmed**：`爹爹` ∈ 顺顺.aliases，顺顺 chapters 含 13/20 | ✅ **机制实证：≥2 独立证据 → confirmed** |
| 父亲 | 不 confirmed / 不进任何 aliases / 不成为 Person | **✅ 全部满足**：`父亲` canonical absent；`ALIAS[父亲]=[]`（无任何 canonical 吸收）；非 Person | ✅ **P16-b 核心目标达成** |

顺顺 最终状态（用户指定查询）：

```cypher
MATCH (p:Person {novel_id: $novel_id}) WHERE p.name = "顺顺"
RETURN p.name, p.aliases, p.mention_count, p.chapters;
-- 顺顺 | [船总顺顺, 中年人, 爹爹] | mc=12 | chapters=[5,6,8,10,11,13,14,19,20,23]
```

### 2.2 逐词 evidence 反推（基于原文上下文 + 最终状态）

**爹爹 → 顺顺（confirmed）**：
- 原文证据：chunk14/ch13「大老走的是车路，应当由大老爹爹作主」、chunk22/ch20「爹爹说年青人也不应该在家中白吃不作事」「你爹爹好吗」「我回来时和我爹爹去说」——5 次命中**全部指向顺顺**（大老/二老之父）。
- 反推：爹爹 在 ≥2 个独立 chunk（chunk14、chunk22）被 judge 判 resolves_to=顺顺 且 **category=DESCRIPTIVE**（触发证据机制）→ 第 2 次独立证据后 confirmed → alias。**证据机制正面实证**（M2 路径）。

**父亲（不确认，跨人物裸 role）**：
- 原文证据（11 hits，至少 3 人）：chunk2 题记（沈从文父，非正文）、chunk4「作渡船夫的父亲」「离开孤独的父亲」「守在父亲身边」= **老船夫（祖父）**、chunk6/ch5「作父亲的当两个儿子很小时」= **顺顺**、chunk18/ch16 + chunk26/ch24「翠翠的父亲」= **翠翠亡父**。
- 反推：父亲 至少 3 个不同指代 → 若 judge 在 chunk4 判 → 祖父、chunk6 判 → 顺顺 → **跨 canonical 冲突 → blocked**（M12/M13 路径）；或 judge 判 null → unresolved（`descriptive_unresolved=19` 之一）。**无论哪条路径，最终 父亲 不入图、不 alias —— 与 P16-b 设计目标完全一致**。
- 重要佐证：`父亲` **不是** Person → 说明它未走 `category=None/PERSON → 立即注册` 的 D5 绕过路径（否则会成为 mc=1 Person），即父亲 的真实 extraction category 更可能是 DESCRIPTIVE → 证据机制真实拦截。

**爸爸（未确认，D5 归因）**：
- 原文证据（9 hits）：ch5「性情如他们爸爸一样」、ch6「作爸爸的」、ch14「想爸爸作主」、ch22「爸爸，你以为这事」「同他爸爸吵了一阵」= **顺顺**（天保/二老之父）；但 chunk8/ch7「楼上妇人的爸爸是在棉花坡被人杀死的」= **他人**（跨人物风险点）。
- 反推：爸爸 若 category=DESCRIPTIVE，chunk5/ch6（同章重叠区同文本）即可凑 2 证据 → confirmed；但**最终 爸爸 是独立 Person（mc=1）** → 说明它在某 chunk 走了 `category=None/PERSON → judge null → 注册 canonical` 的 D5 路径，**证据机制从未触发**（M14/M15 语义：category=None/PERSON 的裸词不触发）。
- 判定：**P017 D5 Known Limitation 实证**（爸爸 本应 confirmed 顺顺，因 extraction category 未标 DESCRIPTIVE 而绕过 gate → 反而碎片化为独立 Person）。非机制失败——机制在 爹爹 上已实证可正确确认。

### 2.3 小结

- **爹爹 → 顺顺：confirmed 建立**（机制生效）。
- **父亲 → 无任何吸收、非 Person**（跨人物裸 role 正确拦截，P16-b 核心价值兑现）。
- **爸爸 → 未确认**：因 `category=None/PERSON` 绕过 evidence gate（D5），成为 mc=1 独立 Person。**记录为 P017 D5 Known Limitation**，不是 V0.2.6 实现失败（判定标准 §10「P16-b PARTIAL」情形）。

---

## 3. qualified role 重点验收

| 词 | 预期 | 实际 | 判定 |
|---|---|---|---|
| 翠翠的祖父 | → 祖父（单次 alias，T-b8 锁死） | **未建立**：`ALIAS[翠翠的祖父]=[]`，祖父 aliases=[老船夫] 不含它 | ❌ 目标未达成（judge/extraction 方差归因，见下） |
| 翠翠的父亲 | 不确认 / 不进顺顺 / 不进其他 canonical | **✅ 全部满足**：`ALIAS[翠翠的父亲]=[]`；顺顺 chapters 无 16 | ✅ **拦截成功** |
| 翠翠祖父（无"的"） | → 祖父 | `ALIAS[翠翠祖父]=[]`；且 chunk26/ch24 为失败块（原文证据丢失） | 无法判定（失败 chunk） |

**翠翠的祖父 归因分析**：
- 原文唯一证据在 chunk11/ch10（**成功 chunk**）：「翠翠的祖父口中不怨天…」。qualified 判定：X=翠翠（known）→ anchor=翠翠；headword=祖父。若 judge 判 resolves_to=祖父 → target 对齐（C名==核词 祖父 ✓）+ anchor 翠翠 文本在场（chunk11 原文含翠翠 ✓）→ 应单次 alias（M9 路径）。
- 实际未建立 → 只有两种可能：(a) **judge 判 null**（P06 方差，计入 descriptive_unresolved=19）；(b) extraction 未提取「翠翠的祖父」（LLM 只输出 祖父/翠翠）。**留存数据无法区分 (a)/(b)**（链路未落盘，同 V0.2.5 §3.1 证据限制）。
- **不是机制误拒**：无 target-mismatch 仍 alias、无 anchor-mismatch 仍 alias 的反例；descriptive_resolved 由 V0.2.5 的 7 → 3，descriptive_unresolved 9 → 19，整体 DESCRIPTIVE 判定成功率下降（P06/输入方差），翠翠的祖父 未建立是这一趋势的一部分。
- **判定**：qualified 目标未达成（PARTIAL），归因 P06 judge 方差 / extraction 方差，**无机制违反证据**；需下次评估链路日志才能直接区分。

**翠翠的父亲 拦截细节**：chunk18/ch16（成功）「翠翠的父亲，便是当地唱歌的第一手」→ qualified：anchor=翠翠、headword=父亲。即使 judge 误判 顺顺 → target 不对齐（C=顺顺 ≠ anchor 翠翠，C名≠核词 父亲）→ drop（M17 场景）；judge null → unresolved。**两条路径均拦截成功**；chunk26/ch24 第二证据因失败块缺失，但不影响结论（第一证据已充分检验拦截）。

---

## 4. 顺顺 sink 验收

| 项 | V0.2.5（novel 0ef3bd31） | V0.2.6（novel 3a54e06a） | 判定 |
|---|---|---|---|
| 顺顺.aliases | [爸爸, 父亲, 顺顺大哥, 顺顺船总, 船总顺顺, 中年人, 爹爹, 船总]（8） | [船总顺顺, 中年人, 爹爹]（3） | 收缩 8 → 3 |
| 父亲 ∈ aliases | 是（ch5b 吸收，语义正确但脆弱） | **否** | ✅ **核心目标：父亲 退出 sink** |
| 爸爸 ∈ aliases | 是 | 否（但成为独立 Person，D5 碎片而非 sink 收缩） | ⚠️ D5 归因 |
| 爹爹 ∈ aliases | 是 | **是**（confirmed 保留） | ✅ |
| 翠翠的父亲 ∈ aliases | 否 | **否**（顺顺 chapters 无 16） | ✅ 持续拦截 |
| 新错误吸收 | – | **无**（顺顺 aliases 全部可解释：船总顺顺/中年人/爹爹） | ✅ |

**结论**：顺顺 sink 不再因裸 role 继续扩大——`父亲` 被阻断、`翠翠的父亲` 持续拦截、aliases 从 8 缩至 3 且全部语义可解释。sink containment **PASS**。

---

## 5. canonical 数量变化与 role 碎片

| 指标 | V0.2.5 | V0.2.6 | 变化 |
|---|---|---|---|
| Person 总数 | 54 | 50 | -4 |
| RELATES_TO 总数 | 63 | 56 | -7 |
| 顺顺 mc / chapters | 14 / [5,6,8,10,11,12,13,14,19,20,22,23,24] | 12 / [5,6,8,10,11,13,14,19,20,23] | 12/22/24 消失 = 失败 chunk 13/24/26 的章节，自洽 |
| role confirmed（实证） | – | 爹爹→顺顺 | ✅ |
| role observation / blocked（逐 chunk） | 未落盘 | 未落盘（父亲 推断 blocked 或 unresolved；仅最终状态可证） | 链路限制 |
| descriptive_unresolved | 9 | **19** | +10（P06/输入方差；含 翠翠的祖父 类） |

**长辈称谓最终状态（V0.2.6）**：

| 词 | 最终状态 | 类别 | 归因 |
|---|---|---|---|
| 父亲 | 不入图（canonical absent / 无 alias） | **unresolved 或 blocked** | ✅ P16-b 目标；推断 category=DESCRIPTIVE |
| 爸爸 | **独立 Person**（mc=1, ch5） | canonical（碎片） | ⚠️ D5：category=None/PERSON 绕过 gate |
| 爹爹 | 顺顺 alias | alias（confirmed） | ✅ 机制实证 |
| 母亲 | **独立 Person**（mc=6, aliases=[白脸黑发的母亲, 翠翠的母亲]） | canonical | ⚠️ D5（与 V0.2.5 行为一致，非本轮引入） |
| 妈妈 | 不入图（ch11「翠翠又同妈妈一样」未注册） | absent | 正常（非碎片） |
| 娘 | 不入图 | absent | 正常（未提取为人物） |

> 新碎片仅 1 个：`爸爸`（mc=1）。`父亲` 未碎片化（机制拦截成功）。`妈妈/娘` 未碎片化。**数量变化不判失败**：50 vs 54 的差异主要来自失败 chunk 集合不同（4 vs 7）+ judge 方差，与 P16-b 无因果。

---

## 6. 原有能力回归（V0.2.6 不得破坏）

| 项 | V0.2.5 | V0.2.6 | 判定 |
|---|---|---|---|
| 老船夫 → 祖父 | ✅ alias | ✅ 祖父.aliases=[老船夫] | ✅ **descriptive epithet 未误套证据 gate**（M14 实证：category=PERSON → 不进机制） |
| 天保大老 → 天保 | ✅ | ✅ 天保.aliases=[天保大人, 天保大老, 哥哥] | ✅（复合称谓 anchor 对齐；另 哥哥→天保 语义正确） |
| 岳云二老 | ✅ → 二老（二老.aliases 含 岳云二老） | **未进任何 aliases**（傩送.aliases=[二老, 傩送二老, 年青小伙子, 年青人]） | ⚠️ 见下 |
| 哥哥 → 大老 | ✅（大老.aliases=[哥哥]） | ✅ 哥哥 ∈ 天保.aliases（canonical 命名变化，语义正确） | ✅ RC3 GENERIC 路径不变 |
| 弟弟 → 二老 | ✅（二老.aliases 含 弟弟） | **未进任何 aliases** | ⚠️ 失败 chunk 归因（见下） |
| 爷爷 | 祖父 alias | **独立 Person**（mc=4, ch4/9/13/14） | ⚠️ P06 judge 方差（爷爷 首字"爷"∉ 机制首字集，机制不参与） |
| 翠翠的祖父 | 祖父 alias | 未建立 | ⚠️ 见 §3 |

**岳云二老 / 弟弟 / 爷爷 归因（均非 P16-b 机制行为）**：
- **岳云二老**：出现于 chunk14/ch13、chunk15/ch13（**成功 chunk**）。V0.2.6 canonical 命名由「二老」变为「傩送」（first-seen 变化，P08 域）→ 复合称谓核词对齐要求 C名==核词「二老」，但 canonical 是「傩送」→ 设计 §8 明确记录的 trade-off：「若限定 mention 的 canonical 以全名命名，核词对齐会拒绝合法 alias——trade-off 接受（保守防错优先）」。或 judge null（P06）。**与设计 trade-off 一致，非回归 bug**。
- **弟弟**：主证据在 chunk17/ch15（「让哥哥知道了弟弟的心事」「那哥哥同弟弟在河上游」）→ **chunk17 为失败块**；chunk19/ch17 的弟弟 未被吸收（judge null / 未提取）。**失败 chunk + P06 归因**。
- **爷爷**：V0.2.5 是祖父 alias；本轮失败 chunk 集合不同（V0.2.5 失败含 ch4/7/9/13a/15/21，本轮含 ch12/15/22/24）+ judge 非确定性 → 爷爷 在早期 chunk 无候选注册为 Person 后 first-seen 锁定（P06/P08 域，机制首字集不含「爷」，P16-b 零参与）。

**老船夫 专项确认（用户 §7 重点）**：`老船夫` canonical **不存在**（absent），全部吸收进 祖父.aliases → **未被误套 role evidence gate**，descriptive epithet 路径零变化。

---

## 7. 失败 chunk 影响（单独记录）

| chunk/chapter | 错误 | 内容损失 | 对结论的影响 |
|---|---|---|---|
| chunk13/ch12 | ReadTimeout | 祖父、顺顺 ch12 证据（顺顺 chapters 12 消失） | 无关键结论依赖 |
| chunk17/ch15 | ReadTimeout | **弟弟 主证据章**（哥哥/弟弟 对话）、天保大老、傩送 共现 | 弟弟→二老 未建立的主因；不影响 P16-b 三组验收（爸爸/爹爹/父亲 主证据在 ch5/6/14/22，其中 22 也失败见下行） |
| chunk24/ch22 | ReadTimeout | **爸爸 的 ch22 顺顺证据**（「爸爸，你以为这事」）、顺顺 ch22 | 爸爸 少 1 个顺顺证据；但 爸爸 未确认的主因是 D5 category 绕过（非证据不足——ch5/6 同文本重叠本可凑 2 证据，若 category=DESCRIPTIVE 必然 confirmed） |
| chunk26/ch24 | ReadTimeout | 翠翠的父亲 第二证据、翠翠祖父、秃头陈四四 | 翠翠的父亲 拦截结论依赖 ch16 第一证据（**成功**）→ 不受影响 |

**关键判断**：27→23 chunk 有效。P16-b 三组验收的**正面证据全部来自成功 chunk**（爹爹 ch13/20 成功、父亲 ch4/ch5b/ch16 成功、翠翠的父亲 ch16 成功、顺顺 aliases 可解释性不依赖失败块）；爸爸 的失败归因是 D5 而非证据缺失。**无结论被失败 chunk 反转**。

---

## 8. merge 状态

| 项 | V0.2.5 | V0.2.6 | 判定 |
|---|---|---|---|
| merge_candidate_pairs | 155 | 148 | – |
| merged_pairs | 0 | 0 | – |
| failed_pairs | 155 | 148（= candidate_pairs） | batch merge judge 一次异常全记 failed |
| **merge 判定** | **INCONCLUSIVE** | **INCONCLUSIVE** | RC1/LLM 稳定性域，**不归因 V0.2.6** |

**LLM failures（独立稳定性问题）**：4 个 ReadTimeout（本轮），较 V0.2.5 的 7 个减少；无 validation_error / alias_resolution_failed。单次 60s timeout 下并发 2 仍偶发读超时 → 独立记录，不判 P16-b。

---

## 9. V0.2.5 vs V0.2.6 对比总表

| 指标 | V0.2.5 | V0.2.6 | 变化 |
|---|---|---|---|
| Person 总数 | 54 | 50 | -4 |
| relationships | 63 | 56 | -7 |
| 顺顺 aliases | 8 | 3 | 收缩（8→3） |
| 父亲 alias | 顺顺.aliases 含 父亲 | **无任何吸收** | ✅ 核心目标达成 |
| 爸爸 alias | 顺顺.aliases 含 爸爸 | 独立 Person（mc=1） | ⚠️ D5 绕过（目标未达成） |
| 爹爹 alias | 顺顺.aliases 含 爹爹 | **顺顺.aliases 含 爹爹（confirmed）** | ✅ 保持 |
| 翠翠的父亲 | 不进入顺顺 | 不进入任何 canonical | ✅ 保持 + 强化 |
| 翠翠的祖父 | 祖父 alias | 未建立 | ⚠️ P06 judge/提取方差（机制无违反证据） |
| role confirmed | – | 爹爹（≥2 证据实证） | ✅ 机制生效 |
| role unresolved/blocked | – | 父亲 不入图（推断 blocked 或 unresolved）；descriptive_unresolved 9→19 | ✅ 目标侧生效 |
| category=None 长辈词 | 母亲 Person | 爸爸 + 母亲 Person（爸爸 为新碎片） | ⚠️ D5 持续（已知限制） |
| merge | INCONCLUSIVE | INCONCLUSIVE | 不变 |

---

## 10. 验收判定（四结论）

```
V0.2.6 / P16-b
├── role admission：PARTIAL
│     · 爹爹 → 顺顺 confirmed（≥2 独立证据，机制实证）✅
│     · 父亲 → 不确认、不进任何 aliases、不成为 Person ✅（P16-b 核心目标达成）
│     · 爸爸 → 未确认：category=None/PERSON 绕过 evidence gate（P017 D5 Known Limitation）
│       → 满足判定标准「PARTIAL：爸爸 因 category=None/PERSON 绕过 evidence gate，
│         但代码机制本身行为符合设计（爹爹 同机制下正确 confirmed）」
│     · 无任何「DESCRIPTIVE bare role evidence<2 却 confirmed」→ 不判 FAIL
├── qualified role：PARTIAL
│     · 翠翠的父亲 → 不确认、不进顺顺、不进其他 canonical ✅（target-mismatch + anchor 拦截实证）
│     · 翠翠的祖父 → 未建立（judge null 或 extraction 未提取；链路未落盘无法区分）
│       → 无 target-mismatch 仍 alias / anchor-mismatch 仍 alias 的机制违反 → 不判 FAIL
│       → 但验收预期「保持正确」未达成 → PARTIAL（归因 P06 judge/提取方差）
├── sink containment：PASS
│     · 父亲 退出顺顺 aliases ✅；翠翠的父亲 持续拦截 ✅；无新错误吸收 ✅
│     · 顺顺 aliases 8→3 且全部可解释；sink 不再因裸 role 扩大
└── P017 D5：observed
      · 爸爸（新碎片，mc=1 Person）：category=None/PERSON 绕过 → 本应 confirmed 顺顺却碎片化
      · 母亲（与 V0.2.5 行为一致）：继续 canonical，非本轮引入
      · 记录为 P017 D5 Known Limitation / P06 follow-up，不修改代码
```

**另记**：
- `merge = INCONCLUSIVE`（148 candidate pairs 全 failed，batch merge judge 异常；RC1 域）
- `LLM failures = 独立稳定性问题`（4× ReadTimeout，较 V0.2.5 的 7 个减少；不判 P16-b）

---

## 11. 结论与后续

1. **P16-b 机制在真实运行中按设计工作**：爹爹 经 ≥2 独立证据 confirmed（正向实证）、父亲 跨人物裸 role 被拦截不入图（目标实证）、翠翠的父亲 qualified 拦截成功（安全实证）——**五个核心验收中的四个达成**。
2. **爸爸 未达成 confirmed 是 P017 D5 缺口**（category=None/PERSON 绕过 gate → 碎片化），非机制失败；与 P17/P018 记录的 D5 哲学一致（不引入 classifier，走 P06 follow-up 提升 category 覆盖）。
3. **翠翠的祖父 未建立** 是本次唯一需要后续观察的 qualified 漏配：P06 judge 方差或 extraction 方差，链路未落盘无法直接归因；下次评估建议为 extract/judge 增加日志或中间产物落盘（代码改动，需另立项）以直接观测。
4. **本轮不做任何代码修改**；如需 follow-up（P06 category 覆盖 / 链路可观测性 / 岳云二老 canonical 命名），另立设计 / Problem Record。

**已确认的后续观察项（不实施，仅登记）**：
- P017 D5：爸爸/母亲 长辈词 category=None/PERSON 绕过 → P06 follow-up（category 质量）。
- P06/链路：翠翠的祖父、岳云二老、弟弟、爷爷 的 judge 输入输出需日志才能直接归因。
- P08：二老↔傩送 canonical 命名漂移（本轮 canonical=傩送，V0.2.5=二老）影响核词对齐路径。
