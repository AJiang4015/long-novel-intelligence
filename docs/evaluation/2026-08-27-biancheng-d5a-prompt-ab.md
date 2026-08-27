# Task B D5-a（A-1）Prompt A/B 实验报告 — extraction coverage prompt（2026-08-27）

> **本报告是 V0.2.8（a9a38f9）上 A-1 prompt A/B 实验的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**
> 尤其注意：本报告结论「**B prompt 不被采纳**」仅针对本次实验设计（唯一变量 = `EXTRACTION_SYSTEM_PROMPT`，
> 模型 qwen3.7-flash、温度 0.2、并发 1、同一 EPUB/chunking/hygiene/judge/merge/schema）；B 腿 6 个 chunk
> 发生 judge 网络错误（ConnectError/ReadTimeout），下游指标受混淆，详见 §6。**A prompt（当前 prompt）保持为默认，未固化 B。**

## 1. Environment Baseline（TESTING.md §6）

| 项 | A 腿（当前 prompt） | B 腿（coverage-enhanced prompt） |
|---|---|---|
| Git | `a9a38f9`（D5-b B-1 提交，工作区干净） | 同左（同一基线，仅 prompt 不同） |
| novel_id | `d04f3767-fa48-42f9-9cb2-7ae39f4c2bdc` | `6a731853-64b7-43e2-b504-10872cbdb8b3` |
| job_id | `cec3e578-4514-4317-bd3d-826b68b21d5f` | `00bcff09-fbba-4030-9097-c22207135183` |
| 模型 / 温度 | qwen3.7-flash / 0.2（既有值） | 同左 |
| chunk / overlap / concurrency | 4000 / 400 / 1 | 同左 |
| EPUB / chunking / hygiene / judge / merge / schema | 同一《边城》EPUB / 同一 chunker / 同一 resolver（含 B-1）/ 同一 judge 契约 / 同一 merge / 同一 schema | 同左 |
| ER_LINEAGE | 1 / RAW=1 | 同左 |
| 终态 | completed（**0 failed**），15 Person / 38 RELATES_TO | completed_with_errors（**6 failed**），12 Person / 35 RELATES_TO |
| lineage 文件 | 653,937 B | 664,247 B |
| 唯一变量 | —— | `EXTRACTION_SYSTEM_PROMPT`（§8 附录 B 全文） |

## 2. A/B 设计

- A = `llm_client.py` 当前 `EXTRACTION_SYSTEM_PROMPT`（原样，未修改）。
- B = 当前 prompt + 2 条新增指令（§8 附录）：⑧ 角色/亲属称谓 coverage（明确指向具体人物的裸称谓/限定式
  应抽取并按其指代标 category；无法确定不臆造；泛指/集合维持现状）；⑨ 非人物专名（地名/船名等，如 岳云）
  不得抽取为 character。
- B 不修改 category 架构 / resolver 语义 / 词表 / 不增加 LLM 调用；通过实验脚本在服务器进程内 patch
  `llm_client.EXTRACTION_SYSTEM_PROMPT`（launcher：`.tmp/ab/run_server_with_prompt.py`），**业务代码零改动**。
- 两腿均全新 novel_id/job_id，顺序执行（避免并发 API 负载差异）。

## 3. L1 + L2：extraction coverage 与 category 分布（extraction_raw，27 chunks 两腿均成功落盘）

| word | A raw (chunk:category) | B raw (chunk:category) | 变化 |
|---|---|---|---|
| 爸爸 | —（未提取） | chunk4: **descriptive** | ✅ B 覆盖 +1 chunk（唯一新增） |
| 妈妈 | — | — | 无变化（两腿均未提取） |
| 娘 | — | — | 无变化 |
| 大儿子 | — | — | 无变化 |
| 长子 | — | — | 无变化 |
| 次子 | — | — | 无变化 |
| 哥哥 | chunk19: None | chunk19: generic | category 变化（None→generic），覆盖相同 |
| 翠翠的祖父 | — | — | 无变化（两腿均未提取） |

**结论**：B 的 coverage 提升 = **仅 爸爸（1 chunk）**；目标 8 词中 6 词（妈妈/娘/大儿子/长子/次子/翠翠的祖父）
两腿均未提取，B 未改善。category 层面 B 将更多裸角色称谓标为 descriptive（见 §5：父亲×2、老船夫×7、祖父×9、
母亲 均较 A 增加 descriptive 标注）——prompt 指令在 category 维度生效，但覆盖维度增益极小。

## 4. L3：downstream ER（lineage 终态 + 图中状态）

| word | A | B |
|---|---|---|
| 爸爸 | not_extracted | descriptive → judge null → **null_unresolved（dropped）** |
| 妈妈/娘/大儿子/长子/次子 | not_extracted | not_extracted |
| 哥哥 | None → judge → **alias 天保**（图：天保.aliases 含 哥哥） | generic → judge（网络错误，chunk19）→ exception 路径 → **dropped** |
| 翠翠的祖父 | not_extracted | not_extracted |
| 全局 | persons 15 / mc=1 碎片 5 / descriptive_unresolved **7** | persons 12 / mc=1 碎片 4 / descriptive_unresolved **33** |

**结论**：B 的 coverage 提升没有转化为下游吸收——爸爸 被提取但 judge null → unresolved（不入图）；
哥哥 在 B 中丢失 alias（受 chunk19 网络错误混淆）；descriptive_unresolved 33 vs 7（大幅恶化，含 6 个失败
chunk 的 exception 路径贡献，见 §6）。**B 未能在 downstream 上优于 A。**

## 5. L4：regression（父亲/爹爹/母亲/老船夫/祖父/顺顺 + 岳云 跨实体污染）

| word | A raw cat | B raw cat | A graph | B graph |
|---|---|---|---|---|
| 父亲 | generic | **descriptive ×2** | absent | absent ✅（两腿均不入图） |
| 爹爹 | 未提取 | **person**（chunk22） | absent | **canonical mc=1** ⚠️ 新碎片（V0.2.6 曾 confirmed 顺顺；B 标 person 绕过 gate + 该 chunk 网络失败 → exception fallback 注册） |
| 母亲 | person | descriptive + generic | **canonical mc=5**（碎片，V0.2.5/6 同型） | **absent**（未碎片化 ✅，但实体未吸收，信息损失） |
| 老船夫 | descriptive×3/person×7/… | descriptive×7/person×5/… | 吸收进 祖父 ✅ | 吸收进 祖父 ✅（两腿均正确） |
| 祖父 | person 主 | person/descriptive 混合 | canonical mc=19 aliases=[爷爷, 老船夫, 伯伯, 老的] | canonical mc=16 aliases=[老船夫, 爷爷, 老头子]（吸收面略窄） |
| 顺顺 | person×10 | person×13 | canonical mc=14 aliases=[顺顺大哥, 船总顺顺, 船总] | canonical mc=13 aliases=[船总顺顺]（**顺顺大哥/船总 吸收丢失** ⚠️） |
| 岳云（地名） | **person**（chunk8） | **person**（chunk8） | 吸收进 傩送 ⚠️ | 吸收进 傩送 ⚠️（**跨实体污染两腿均存在**，B 的 ⑨ 指令未阻止提取） |

**结论**：父亲/老船夫 的 P16-b 路径两腿均正确；但 B 引入 爹爹 person 误标 → mc=1 碎片（回归），顺顺 吸收面
收窄（顺顺大哥/船总 丢失），岳云 跨实体污染未改善。**B 在 regression 上未优于 A，且新增一处爹爹碎片。**

## 6. 混淆变量披露（B 腿 judge 网络错误）

B 腿 6 个失败块（chunk 19/22/23/24/25/26）均为 `alias_resolution_failed`，lineage judge 事件显示
**ConnectError×21 + ReadTimeout×2**（纯网络层错误，非 validation/非 prompt 直接产物）。A 腿 0 failed。
影响：
- B 的 descriptive_unresolved=33 中，6 个失败 chunk 的 DESCRIPTIVE pending 全部经 exception 路径 →
  unresolved（`_register_or_unresolved` 语义），**显著虚增**；真实 judge-null 贡献需 B 重跑分离。
- 爹爹 mc=1 碎片发生在 chunk22（失败块）→ exception fallback（person + judge 网络错误 → fail-safe 注册），
  不能完全归因于 prompt 的 person 标注。
- **下游（L3/L4）结论以「受混淆、方向性参考」对待**；extraction 层（L1/L2，27/27 raw 成功）结论有效。

## 7. 结论与决策

**B prompt 不被采纳（保持 A = 当前 prompt 为默认）**。三项验收标准：

| 标准 | 结果 | 依据 |
|---|---|---|
| coverage 优于 A | ❌（勉强） | 仅 爸爸 +1 chunk；6/8 目标词两腿均未提取 |
| downstream quality 优于 A | ❌ | 爸爸 提取但 unresolved 不入图；哥哥 alias 丢失；descriptive_unresolved 7→33（含混淆）；persons 15→12 |
| regression 无退化 | ❌ | 爹爹 person 误标 → mc=1 新碎片；顺顺 aliases 收窄（顺顺大哥/船总 丢失）；岳云 污染未改善 |

- **A prompt 保持**；B prompt 全文仅记录于本报告 §8 附录（实验产物 `.tmp/ab/prompt_b_coverage.txt` 亦保留，
  未写入 `llm_client.py`）。
- D5-a 的 extraction coverage 缺失（妈妈/娘/大儿子/长子/次子/翠翠的祖父 未提取）在当前 prompt + 模型
  （qwen3.7-flash）下**未被本次 prompt 增强修复**——覆盖问题更可能依赖模型选择（P06 提取方差），prompt
  coverage 的边际收益有限且伴随 descriptive 化风险。
- Follow-up 候选（另立评审）：① B 重跑一次以分离网络混淆（成本 ≈ 1 次 ingest）；② 收窄 B 指令（仅限定式 +
  明确指代，不引导裸称谓 descriptive 化，降低 爹爹 误标风险）；③ 接受 extraction 覆盖为模型域（A-2 量化监控
  持续）。本轮不实施。

## 8. 附录：B prompt 全文（coverage-enhanced，未固化）

```
你是小说人物关系抽取器。给定一段小说文本，抽取其中明确出现的人物，以及人物之间明确的关系。
严格要求：
1. 只抽取文本中明确出现的人物与关系，不要臆测。
2. characters: 文本中出现的人物姓名列表（同一人物按文本中的写法输出，不要合并别名）。
3. relationships: 人物之间的关系。source 是当前文本片段中作为关系主体的人物，target 是与其发生关系的人物。
4. type 只能使用以下 7 个枚举值之一：love（爱情）、family（血缘/家族）、friendship（友谊）、enmity（敌对/仇怨）、alliance（结盟/合作）、mentorship（师徒/师生）、other（其他无法归类的明确关系）。禁止自创类型，如 romantic、lover、亲密、爱情、love_relation 等一律归入 love。
5. confidence: 0 到 1 之间的浮点数，表示你对这条关系判断的把握程度。
6. category（可选）: 每个 character 可附 category，取值 person/generic/collective/descriptive/composite/invalid。
   - person: 专名（天保、傩送、翠翠）
   - generic: 泛指称谓（年青人、妇人、哥哥、弟弟）
   - descriptive: 描述性称谓（翠翠的祖父）
   - composite: 复合称谓（岳云二老、天保大老、天保大人）
   - invalid: 畸形输入
   无法确定时省略 category 字段。
7. 只输出 JSON 对象，不要输出任何其他文字。格式：
{"characters": [{"name": "...", "category": "person"}], "relationships": [{"source": "...", "target": "...", "type": "love", "confidence": 0.9}]}
8. 角色/亲属称谓覆盖（A-1 实验增强）：正文中角色称谓、亲属称谓若在上下文里**明确指向某位具体人物**，应抽取为 character 并按既有定义标 category，不要遗漏：
   - 裸称谓明确指向具体人物（如 爸爸、爹爹、父亲、母亲、妈妈、娘、祖父、爷爷、哥哥、弟弟、大儿子、长子、次子）：按指代对象标 category——能确定为专名指代时 person；描述性指代（"翠翠的祖父"这类结构或依赖亲属关系指代时）descriptive；无法确定指向时省略 category 字段，**不要为了覆盖而臆造抽取**。
   - 限定式（翠翠的祖父、顺顺的弟弟、翠翠的母亲）：descriptive。
   - 泛指/集合（年青人、妇人、两个儿子、兄弟二人）：generic / collective（维持现状）。
9. 非人物专名（地名、船名、书名、店名等，如 岳云、白河、边城）除非上下文明确将其人格化，否则**不得**抽取为 character；不要把它们当作人物。
```
