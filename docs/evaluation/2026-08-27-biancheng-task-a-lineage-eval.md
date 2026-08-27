# Task A（P06 Lineage）真实《边城》验收报告 — lineage 归层（2026-08-27）

> **本报告是 V0.2.7 Task A（lineage 观测）的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**
> 尤其注意：本报告给出的四案例归层与 Task B 归属结论，仅基于本次 `ER_LINEAGE=1` 运行（qwen3.7-flash）的
> lineage 事实；模型与 V0.2.6 不同（V0.2.6 = qwen3.7-max-2026-06-08，本轮 = qwen3.7-flash，用户指定），
> 跨模型结论差异属 LLM 非确定性域（P06），不作为确定性事实外推。

## 1. Environment Baseline

| 项 | 值 |
|---|---|
| job_id | `ac8f7d67-d21d-4c15-94ee-15e5c90e5e6e` |
| novel_id | `858e0ecf-29a3-4df8-b99d-7f34e7f41d3f` |
| 小说 | 《边城》(沈从文)，25 chapters / 27 chunks（同一 EPUB） |
| Git | HEAD=`8de14a1`（V0.2.7 Task A 实现提交） |
| 模型 | `qwen3.7-flash`（用户指定；V0.2.6 基线为 qwen3.7-max-2026-06-08） |
| chunk_size / overlap / concurrency | 4000 / 400 / **1**（用户指定；V0.2.6 为 2） |
| Neo4j | novel-neo4j（5.26.x Community，bolt://192.168.127.101:7687） |
| ER_LINEAGE / RAW / DIR | 1 / 1 / `../.tmp/lineage`（真实评估显式开启；代码默认关闭） |
| 终态 | **completed（0 failed blocks，27/27 chunk 成功）**；32 Person / 53 RELATES_TO |
| lineage 文件 | `.tmp/lineage/858e0ecf-….jsonl`，**633,392 B**（< 5MB ✓），1574 事件 |

**stats**：`merge_candidate_pairs=132 / merged=0 / failed=132`（batch merge judge 再次整体失败 → merge
**INCONCLUSIVE**，RC1/LLM 稳定性域，与 V0.2.5/V0.2.6 同模式）；
`mention_hygiene = {collective_filtered:0, generic_filtered:8, descriptive_resolved:1, composite_resolved:2,
invalid_filtered:0, nonbody_person_provisional:4, nonbody_descriptive_dropped:0, nonbody_provisional_dropped:4,
descriptive_unresolved:5, composite_unresolved:2}`。

**事件统计**：extraction_raw 27 / chunk_start 27 / mention_enter 182 / recall 456 / admission 402 /
registration 402 / judge_batch 18 / judge 57 / merge_stats 1 / canonical_snapshot 1 / job_end 1。

## 2. 验收项 1：lineage 产物存在且含全字段

- `<novel_id>.jsonl` 存在（633KB）；mention 事件（mention_enter/recall/judge/admission/registration）
  全部携带 `lineage_id`，且同一 (mention, chunk) 处理实例的五层事件共享同一 id（实测：如 岳云二老
  chunk14 的 5 层事件同一 lineage `0bcde45d…`）——**lineage_id 显式 join 成立，不依赖 (chunk_id, mention)**。
- 全部 §3 字段（extraction_category / hygiene_category / role_* / recall_* / judge_* / admission_* /
  evidence_count / registered / alias_to / final_canonical / merge_drop / canonical_snapshot / job_end）落盘。

## 3. 验收项 2：四案例逐项归层（唯一故障层 + 决定性证据）

### 3.1 翠翠的祖父 → **EXTRACTION_LAYER（extraction 层：LLM 未提取）**

| 层 | 事实（lineage 决定性证据） |
|---|---|
| ① extraction | **全文件 1574 事件中该 mention 出现 0 次**；`extraction_raw`（27 chunks 全量 characters/relationships dump）**零出现**；无任何 mention_enter |
| ②-⑥ | 无事件（未进入 recall/judge/admission/registration） |
| 图终态 | ABSENT（canonical 与 aliases 均无） |

**结论**：V0.2.6 未决问题「(a) judge 判 null vs (b) extraction 未提取」→ **实测为 (b)**。原文唯一证据
chunk11/ch10「翠翠的祖父口中不怨天」在本模型下未被提取为人物。属 P06 提取方差，**与 P16-b gate / judge /
category 无关**。工具输出：`grep '"mention": "翠翠的祖父"'` 无命中 → `EXTRACTION_LAYER`。

### 3.2 岳云二老 → **SUCCESS（→ 傩送 alias）**

lineage `0bcde45d`（chunk14/ch13）：
`extraction_category=composite`（标注正确）→ recall strong（candidates 含 傩送；role=qualified/傩送/二老——
岳云 已为 傩送 别名 → 前缀对齐）→ judge resolves_to=傩送 → admission=accept → registration alias_to=傩送。
图终态：`傩送.aliases = [二老, 傩送二老, 岳云, 岳云二老, 年青人, 弟弟]` ✓（吸收链完整）。
**V0.2.6「未进任何 aliases」在本模型下不复现**（该轮归因 judge/提取方差，本轮 lineage 证实前两层标注
正确、judge 正确 → 成功路径）。

### 3.3 弟弟 → **SUCCESS（→ 傩送 alias；期望 二老 为同一 canonical 别名变体）**

lineage `d1f33c55`（chunk19/ch17）：
`extraction_category=generic`（RC3 hygiene 亦 generic）→ recall strong（candidates 含 傩送）→
judge resolves_to=傩送 → admission=accept → registration alias_to=傩送。
图终态：`傩送.aliases` 含 弟弟 ✓。诊断工具按 canonical_snapshot 判定「二老 ∈ 傩送.aliases」→ 期望满足
（v2.1 别名变体比较，见 §5）。

### 3.4 爷爷 → **SUCCESS（→ 祖父 alias，后续全 known_hit）**

首现 lineage `bbcefa13`（chunk8/ch7）：`extraction_category=person` → recall strong（candidates 含 祖父）→
judge resolves_to=祖父 → admission=accept → registration alias_to=祖父。此后 10 个 chunk 全部
`recall_source=known_hit`（映射稳定保持）。图终态：`祖父.aliases = [爷爷, 伯伯]` ✓。
**V0.2.6「爷爷 独立 Person（mc=4）」在本模型下不复现**——该轮归因 judge 方差 + 失败 chunk；本轮 0 失败块 +
judge 正确 → 成功路径。

### 3.5 四案例结论汇总

| 案例 | 本轮归层 | 决定性证据 | 是否落入 V0.2.6 历史故障模式 |
|---|---|---|---|
| 翠翠的祖父 | **EXTRACTION_LAYER** | extraction_raw 27 chunks 零出现；0 事件 | 是（历史无法归层 → 本轮确定为未提取） |
| 岳云二老 | **SUCCESS** | composite 标注 + judge→傩送 + accept + 图内吸收 | 否（本轮成功；历史失败为方差） |
| 弟弟 | **SUCCESS** | generic 标注 + judge→傩送 + accept + 图内吸收 | 否（本轮成功；V0.2.6 主证据 chunk17 曾失败） |
| 爷爷 | **SUCCESS** | person 标注 + judge→祖父 + accept + known_hit 保持 | 否（本轮成功；历史失败为 judge 方差） |

**归层能力验收：四项全部落在唯一层并给出决定性证据链；其中 翠翠的祖父 直接终结了 V0.2.6 的 (a)/(b) 未决问题。**

## 4. Task B 归属结论（据 lineage 事实，不写代码）

按用户给定候选（category missing / category wrong / recall failure / judge variance / admission issue /
registration/merge issue）：

- **四案例中零个**落在 category missing / category wrong / recall / judge / admission / registration/merge 层
  （三个 SUCCESS，一个 EXTRACTION_LAYER）。**翠翠的祖父 不归 Task B**——D5 的前提（mention 被提取但 category
  缺失/错误）不成立，它是 extraction 覆盖缺失（P06 提取方差）。
- **Task B（P017 D5）量化前置数据已采集**（本轮 lineage + extraction_raw 直接观测）：
  - `爸爸` / `妈妈` / `娘` / `大儿子` / `长子` / `次子`：**未提取**（extraction_raw 零出现）→ V0.2.6 对
    「爸爸 category=None/PERSON 绕过 gate」的推断在本模型下不成立（根本没进 extraction），**extraction
    覆盖缺失是首要事实**；
  - `爹爹`：正确标 `descriptive` → gate 触发 → observation（仅 1 证据，未 confirmed）——**P16-b 机制正常**；
  - `父亲`：LLM 标 `generic` → 无候选丢弃（不入图）；
  - `母亲`：LLM 标 `generic`，chunk6 judge null → **`null_registered` 成为 canonical（mc=7, aliases=
    [翠翠的母亲, 妇人]）**——**LLM generic 标签在 judge-null 路径未被尊重**（`_apply_judge` 的 GENERIC-null
    分支只认 hygiene 词表，不认 LLM category），母亲 碎片化照旧。
- **→ Task B 归属**：本轮事实不支持「四案例 = category missing/wrong」；真正的可立项缺口是
  **(a) extraction 覆盖缺失（翠翠的祖父/爸爸/大儿子一族 未提取）** 与 **(b) LLM 标注类别在 null 路径的
  语义一致性（母亲 generic 标签无效）**。Task B（若继续 D5 category coverage 方向）应把这两个事实纳入
  问题边界与量化指标；是否归 D5 / 另立「extraction 覆盖」Problem Record，需在新设计中评审（本报告不下修复方案）。

**另记（非四案例验收范围，lineage 顺带揭示）**：`老船夫` 本轮为独立 canonical（mc=14，未吸收进 祖父；
V0.2.6 为 祖父.aliases 成员）——P08/P06 零重合分裂域，需单独评估；`岳云`（地名）被吸收进 傩送.aliases，
存在跨实体错吸风险（P08），同样超出四案例验收。

## 5. 验证中修复的一个工具缺陷（诊断工具 v2.1）

真实数据暴露：期望值比较仅支持「alias/canonical 直等于期望」。`弟弟` 实际 alias 傩送、期望 二老 时误报
UNKNOWN（二老 是 傩送 的别名）。已修复 `tools/diagnose_lineage.py`：新增 `_expect_satisfied`——期望 ∈ 该
canonical 的 aliases（canonical_snapshot）即判满足；新增单测 `test_diagnose_expect_variant_alias_success`。
**纯诊断工具改动，不影响 recorder/业务判定。**

## 6. 其他验收项

| 验收项（spec §8） | 结果 |
|---|---|
| 1. lineage 文件存在且含全字段（lineage_id 全层 join） | ✅ 633KB / 1574 事件 / 五层共享 lineage_id |
| 2. 四案例逐项归层（唯一层 + 证据链） | ✅ §3（一项 EXTRACTION_LAYER，三项 SUCCESS） |
| 3. ER_LINEAGE 关闭时回归不变 | ✅ unit 224（207+17）/ integration 15 全绿（默认 off 零行为） |
| 4. 无新增 LLM 调用；文件 < 5MB | ✅ 事件数 = 既有调用数；633KB |
| 5. 判定文件仅旁路打点、无逻辑改动 | ✅ git diff 仅 2 处替换（构造签名扩展 + except as exc） |
| 附：diagnose_lineage 离线归层 | ✅ 四案例 + 全量 mention 均可（`--all`） |

## 7. 环境变更记录（影响后续运行）

- `backend/.env`：`BAILIAN_MODEL=qwen3.7-flash`（用户指定，替代 V0.2.6 的 qwen3.7-max-2026-06-08）、
  `LLM_CONCURRENCY=1`（用户指定，原 2）、追加 `ER_LINEAGE=1 / ER_LINEAGE_RAW_EXTRACTION=1 /
  ER_LINEAGE_DIR=../.tmp/lineage`（真实评估显式开启；代码默认关闭）。
- 运行后端端口 8001（8000 被间歇性占用）。lineage 产物在 `.tmp/lineage/`（gitignored，保留审计）。

## 8. 结论

1. **Task A 验收通过**：lineage 观测在真实运行中完成了四历史案例的确定性归层；`翠翠的祖父` 确定为
   extraction 未提取（终结 V0.2.6 未决问题），其余三案例本轮成功路径完整可见。
2. **Task B 决策输入已就绪**：四案例不指向 category missing/wrong；新事实 = extraction 覆盖缺失 +
   LLM category 在 null 路径的语义不一致（母亲）。Task B 立项时需据此修订问题边界（另立设计，本报告不改代码）。
3. 工具缺陷（别名变体比较）已修复并回归（18 lineage unit 全绿）。
