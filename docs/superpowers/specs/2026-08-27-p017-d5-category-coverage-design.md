# Task B v2：P017 D5 问题重划分 — extraction coverage（D5-a）与 null 路径类别不一致（D5-b）

- **日期**: 2026-08-27（v2，基于 Task A 真实 lineage 事实重写）
- **版本**: v2.1（**D5-b / B-1 已实施并通过验收**，见 §9；D5-a / A-1 待独立 A/B）
- **状态**: D5-b 实现中→✅ 已验收（commit 见 git log）；D5-a 设计评审中（只评审不实现）
- **前置**: Task A 真实验收 `docs/evaluation/2026-08-27-biancheng-task-a-lineage-eval.md`（qwen3.7-flash，
  27/27 chunk 成功，lineage 633KB）；v1 为本文件历史版本
- **约束（沿用）**: 不修改 P16-b gate / 不引入 classifier / 不扩 generic 词表（P16/P018 Do Not Reopen）/
  不增加 LLM 调用 / 不改 schema / 不改 prompt（除方案 A-1 需独立 A/B 评审）。

## 0. 必须修正的两个旧假设（Task A 真实验证推翻/降级）

| # | v1 假设 | Task A 事实（lineage + extraction_raw 直接观测） | 处理 |
|---|---|---|---|
| 1 | 爸爸 = 「category=None/PERSON 绕过 evidence gate」（V0.2.6 推断） | 本轮 `extraction_raw`（27 chunks 全量 dump）**爸爸 零出现**——该模型（qwen3.7-flash）根本未提取 爸爸 | **降级为历史推断**（仅对 V0.2.6 的 qwen3.7-max 成立），不再作为当前事实 / 不再驱动 gate 修改 |
| 2 | 翠翠的祖父 = P06 judge/admission 问题（无法区分 judge null vs 未提取） | **EXTRACTION_LAYER 定案**：全文件 0 事件、extraction_raw 零出现 → LLM 未提取 | **从 P06 judge/admission 域移除**；不再用于推动 resolver/gate 修改；如需修复归入 D5-a 的覆盖清单 |

## 1. 问题地图重划分：P017 D5 域 = D5（原义）+ D5-a + D5-b

P017 的 D5 子项（V0.2.4-V0.2.6 记录：extraction category 覆盖率与质量）经 Task A 事实拆为三个
**机制独立、修复面独立**的缺口；共享父问题（category 层缺口 → 碎片化/信息损失）与共享约束。

| 子项 | 现象（本轮 lineage 事实） | 机制层 | 性质 |
|---|---|---|---|
| **D5（原义）** | 被提取但 category=None → judge null → `legacy PERSON fallback` 注册 canonical | resolver `_register_or_unresolved`（None → `_register_mention` → `_register`） | **设计性 Known Limitation**（P017 D2「兜底不静默丢人物」；代码路径仍存在，**本轮无直接观察案例**——老船夫/祖父 首现均为 person 非 None） |
| **D5-a** | **extraction mention coverage 缺失**：爸爸 / 妈妈 / 娘 / 大儿子 / 长子 / 次子 / 哥哥（+ 翠翠的祖父）未出现在 extraction_raw | **extraction 输出层**（模型输出选择；V0.2.6 的 qwen3.7-max 部分词有输出 → 模型间方差） | 新拆分；修复面 = prompt coverage / 模型，**非 resolver** |
| **D5-b** | **LLM generic 标签在 judge-null fallback 路径未生效**：母亲 被提取且 LLM 标 generic，chunk6 judge null → 仍注册 canonical（mc=7, aliases=[翠翠的母亲, 妇人]） | resolver `_apply_judge` null 分支与 `_resolve_name` 的 effective-category 判定**不一致** | 新拆分；修复面 = resolver 内部一致性（一行级），**不改 gate** |

**划分结论**：A（D5-a）与 B（D5-b）**同属 P017 D5 域，但拆成两个独立子项**——共享主题与约束
（category 层缺口、不扩词表、不改 gate），但机制层（extraction 输出 vs resolver fallback）与修复面
（prompt A/B vs 代码一致性）完全不同，合在一起无法统一验收/回滚。

---

## 2. A（D5-a）：relational/generic mention extraction coverage 缺失

### 2.1 归层：extraction coverage，不是 category 标注问题

- 现象层：mention **未出现在 extraction 输出**（extraction_raw 零出现）——发生在 category 判定**之前**。
- 因此 A **不是**「category missing / category wrong」（那些要求 mention 已提取）。
- A **不是 extraction contract 缺口**：契约（`MentionCategory` 枚举 + `ExtractionResult`）已支持全部
  相关类别——爹爹(descriptive)/父亲(generic)/母亲(generic)/祖父(person)/老船夫(person) 本轮均成功
  输出且带类别。contract 无缺口。
- A 的归层 = **extraction coverage（模型输出选择）**；修复手段 = **prompt coverage**（提示词覆盖，
  指示模型抽取角色称谓）或模型选择/温度——均为「提示/覆盖」域。
- 跨模型证据：V0.2.6（qwen3.7-max）爸爸 9 hits 被提取；本轮（qwen3.7-flash）零输出 → 覆盖随模型漂移
  （P06 提取方差），证明是 extraction 层行为而非下游机制。

### 2.2 候选方案（不改 P16-b gate）

| 方案 | 做法 | 优点 | 风险/代价 |
|---|---|---|---|
| **A-1 prompt coverage 增强** | `EXTRACTION_SYSTEM_PROMPT` 增补裸角色称谓/亲属称谓抽取指示 + 示例（如 爸爸→顺顺 同型、翠翠的祖父→祖父）；明确「指向具体人物时抽取」 | 直接改善源头覆盖；可回滚；不动判定 | 影响**全部** extraction（A/B 对照必须）；可能提高泛指词输出量（妈妈/儿子…）→ 需 hygiene/generic 兜底核验；老船夫/祖父 等 epithet 需 A/B 跟踪（见 §4） |
| **A-2 零代码量化监控** | lineage + `diagnose_lineage --all` 已可输出「未提取 mention 清单」；每轮评估报告固定输出覆盖统计 | 零代码；立即可用 | 不修复覆盖，仅量化 |
| **A-3 二段式补抽** | 对未提取的候选 mention 二次询问 | 精准补漏 | **增加 LLM 调用**，违反「零额外调用」约束 → 排除/远期 |

---

## 3. B（D5-b）：LLM generic 标签在 judge-null fallback 路径不一致

### 3.1 精确 fallback 路径（resolver.py）

```
judge 返回 resolves_to=null
  → _apply_judge  null 分支：
      if r.resolves_to is None and classify_mention(r.mention) == MentionCategory.GENERIC:
          continue            # ← 只查 hygiene 词表（_RELATIONAL_GENERIC_WORDS：兄弟/哥哥/弟弟/…）
      if r.resolves_to is None:
          self._register_or_unresolved(r.mention)   # 母亲：classify_mention(母亲)=None（不在词表）→ 走到这里
  → _register_or_unresolved(母亲):
      cat = self._category_of(母亲) = GENERIC（LLM 标注）   # 非 DESCRIPTIVE/COMPOSITE
      → 不 unresolved → _register_mention(母亲)
  → _register_mention(母亲): BODY → _register(母亲) → canonical（known["母亲"]="母亲"，mc=7）
```

### 3.2 根因：两处 effective-category 判定不一致

- `_resolve_name`（无候选分支）用 **effective category**：`hy_cat = classify_mention(name)`；
  `cat = GENERIC if hy_cat==GENERIC else self._category_of(name)` → **LLM generic 被尊重**
  （`if cat == GENERIC: generic_filtered++; return name, False` 丢弃）。本轮 父亲（LLM generic、
  无候选）即由此丢弃 ✓。
- `_apply_judge`（judge-null 分支）**只查 hygiene 词表**（`classify_mention`），不查 LLM category →
  LLM generic + judge null → 仍注册。本轮 母亲（LLM generic、有候选 → judge null）即由此注册 ✗。
- 历史原因：RC3（V0.2.4-b）刻意「只信词表不信 LLM category」（P09 教训），但该原则只落实在
  `_resolve_name`/无候选路径，**漏了 judge-null 路径**——两处语义漂移。

### 3.3 附带输出泄漏（B-1 必须一并处理）

- resolve() 尾部的输出剔除集合同样只查 hygiene 词表：
  `dropped = {p.mention for p in pending if p.mention not in self.known and classify_mention(p.mention)==GENERIC}`
- 即使 B-1 在 null 分支跳过注册，母亲 不在 known、又不在 dropped → **以原名残留在 resolved_chars** →
  `merge_extractions` 仍会为它建 Person 节点（merger 对 characters 内任何名字建 PersonAgg）。
- 因此 B-1 修复必须同步：null 分支跳过时显式 `self._chunk_dropped.add(r.mention)`（或把 dropped 条件
  对齐 effective category），否则只是「不注册但仍入图」，验收无法闭环。

### 3.4 候选方案（不改 P16-b gate）

| 方案 | 做法 | 影响 | 风险/代价 |
|---|---|---|---|
| **B-1（推荐，最小侵入）** | `_apply_judge` null 分支改用与 `_resolve_name` 一致的 effective category（hygiene 词表 OR LLM generic → 丢弃不注册）+ dropped/`_chunk_dropped` 对齐防输出泄漏 | 母亲 类不再碎片化（V0.2.5/6 母亲 canonical mc=6/7 → 新行为 dropped）——**行为变更需评估声明 + 新单测** | 纯 resolver 内部一致性；不动 gate/prompt/schema；见 §4/§5 影响面 |
| **B-2 扩 hygiene 词表**（母亲/爸爸/父亲 入 `_RELATIONAL_GENERIC_WORDS`） | — | 母亲 类直接走词表 GENERIC | **P16/P018 Do Not Reopen 明确禁止**（「不把 父亲/母亲/祖父 加入 generic 词表」）→ 排除 |
| **B-3 保持现状 + 文档化** | 继续注册，lineage 量化 | 母亲 持续碎片化 | 信息损失继续（与 P16-b「首次信息损失」trade-off 同哲学，可接受则选） |

---

## 4. 对 老船夫 等合法 PERSON/epithet 的影响

| 方案 | 是否影响 老船夫 / 祖父 / 顺顺 等合法 PERSON/epithet |
|---|---|
| **B-1** | **不影响**。老船夫 本轮 14 次 entry 的 category 为 person/descriptive/None，**从未被 LLM 标 generic**；其分裂（chunk4 judge null → null_registered → first-seen 锁定，mc=14 未吸收进 祖父）是 **P06/P08 judge 方差 + 零重合召回**域，独立处理，与 B-1 无交集 |
| **A-1** | **可能影响（全局 prompt）**：必须 A/B 对照跟踪 老船夫/祖父/顺顺 的 category 分布与吸收路径，确认 epithet 仍走 judge→祖父 而非新碎片化（本轮老船夫 已分裂，A/B 需确认不恶化） |
| **B-2** | 会直接误伤（父亲/母亲/祖父 若入词表，合法 alias 路径被切断）→ 已排除 |

---

## 5. 对 207 + 15 regression 的影响

| 方案 | 影响 | 依据 |
|---|---|---|
| **B-1** | **预计 0 回归**，但需全量验证 + 补新用例 | 现有 GENERIC 测试全部使用**词表词**（弟弟/哥哥/兄弟 → `classify_mention=GENERIC`，null 分支已跳过）或 judge-pass 路径（年青人→alias）；**无任何用例锁定「LLM generic（非词表）+ judge null → 注册」**（grep 已核：test_resolver_descriptive.py T-b10、test_hygiene.py RC3 组、test_role_policy.py M10 均为词表词）。补：母亲 型用例（LLM generic + judge null → 丢弃 + 输出剔除） |
| **A-1** | unit 不受影响（mock `FakeHttpClient` 固定响应，不感知 prompt 语义）；需核查 `test_llm_client.py` 无 prompt 内容断言（预计无） | prompt 变更只影响真实 LLM 输出 → 真实 A/B 单独评估 |
| **A-2 / B-3** | 零代码 → 零影响 | — |

---

## 6. 最小侵入实施顺序（评审通过后执行；本设计不实现）

```text
Step 1  B-1（确定性机制修复，先行）
        ① _apply_judge null 分支：effective category 对齐（hygiene 词表 OR LLM generic → 丢弃）
        ② dropped/输出剔除对齐（或 null 分支显式 _chunk_dropped.add）防输出泄漏
        ③ 单测：母亲 型（LLM generic + judge null → 不注册 + 输出剔除）+ 词表 generic 回归不变
        ④ 全量 unit 225 + integration 15；真实《边城》ER_LINEAGE=1 重跑，lineage 前后对照 母亲 行为
        （canonical → dropped）与四案例不回归
        理由：不依赖 LLM 行为、可单测、影响面可控 → 先收敛机制缺口

Step 2  A-1（prompt coverage，需真实 A/B）
        ① EXTRACTION_SYSTEM_PROMPT 增补裸角色称谓/亲属称谓抽取指示 + 示例（爸爸→顺顺 同型、
           翠翠的祖父→祖父）
        ② 同一 EPUB 两次 ingest（原 prompt vs 新 prompt）用 lineage 对比：
           category 分布 / 爸爸·大儿子一族·翠翠的祖父 覆盖 / 老船夫·祖父·顺顺 epithet 不回归
        ③ A/B 通过 → 固化 prompt + 评估报告；不通过 → 回退，维持 A-2 监控
        理由：依赖真实 LLM 方差，必须 A/B 决策，后置

Step 3  A-2（全程监控）
        lineage「未提取 mention 清单」作为每轮评估报告标准输出（工具已具备，零代码）

Step 4  D5 原义（category=None → PERSON fallback）
        保持 Known Limitation 文档化；若后续真实评估出现「None 首现 + judge null → 碎片化」直接案例，
        再评估是否收紧（属 P017 D2 trade-off 决策，另立评审）
```

## 7. 验收（v2 的 Done 定义，评审通过后执行）

1. **D5-b**：母亲 型（LLM generic + judge null）→ 不注册 canonical + 输出剔除；词表 GENERIC
   （哥哥/弟弟/兄弟）与 judge-pass 路径（年青人）行为不变；unit 225+新增 / integration 15 全绿；
   真实《边城》重跑 lineage 对照 母亲 由 canonical → dropped，四历史案例归层不回归。
2. **D5-a**：A/B 对照给出 爸爸/大儿子一族/翠翠的祖父 的覆盖前后对比与 epithet 不回归证据；
   决策（固化 prompt / 回退 / 保持监控）有记录。
3. 不修改 P16-b gate（`_role_alias_decision` 与 evidence 机制零接触）；不扩 generic 词表；
   不引入 classifier；不增加 LLM 调用（A-3 排除）。
4. 每轮评估报告固定输出「未提取 relational/generic mention 清单」（A-2）。

## 8. Do Not（v2 追加）

- 不因 翠翠的祖父（EXTRACTION_LAYER 定案）修改 resolver/gate——其修复面在 extraction coverage（D5-a）。
- 不把「爸爸 category=None/PERSON 绕过 gate」当当前事实引用（仅限 V0.2.6 历史推断；Task B 决策以
  lineage 直接观测为准）。
- 不把 D5-a 与 D5-b 混为一个修复（机制/修复面/验收独立）。
- 不在本设计评审前写任何修复代码。

## 9. D5-b / B-1 实施与验收（v2.1，2026-08-27）

**实现**（commit 见 git log，与 A-1 独立提交）：
- `resolver.py` 新增 `_is_effective_generic(name)`：effective category 是否 GENERIC（hygiene 词表
  优先，其次 LLM category——与 `_resolve_name` 的 category precedence 一致）。
- `_apply_judge` null 分支：`classify_mention(...)==GENERIC` → `_is_effective_generic(...)`；
  **同时 `self._chunk_dropped.add(mention)`**——防 resolved_chars 泄漏（LLM generic 非词表词，
  resolve() 尾部 dropped 集合只查 classify_mention，不命中；否则 母亲 会以原名残留并在
  merge_extractions 建成 Person，已实测泄漏）。
- missing-judge 防御路径、judge exception 路径同样对齐（GENERIC 永不 canonicalize 语义全覆盖）。
- **未改**：`_role_alias_decision` / P16-b evidence gate / generic 词表 / prompt / schema；零新增 LLM 调用。

**目标行为（实测确认）**：LLM category=GENERIC + judge null → 不注册 canonical / 不注册 alias /
不进 resolved_chars / 不进 merge_extractions / 图中无独立 Person（lineage: admission=skipped_generic,
reason=generic_null; registration registered=False）。

**控制流确认（实现前实测）**：`judge=null → _apply_judge → (旧) classify_mention 不命中 → 
_register_or_unresolved → _register_mention → _register → canonical`（母亲 型确凿）；
仅改 null 分支不加剔除 → resolved_chars 泄漏 → merger 仍建 Person（子类模拟实证）。

**测试**（unit 228 = 225+3，integration 15 全绿）：
- 新增 `test_llm_generic_judge_null_dropped_not_canonical`（母亲 型全链：不注册/不进输出/无 Person）
- 新增 `test_llm_generic_judge_pass_alias_unchanged`（judge pass → alias 不变）
- 新增 `test_lineage_llm_generic_judge_null_skipped`（lineage 事件断言）
- 已有回归不变：词表 GENERIC + judge null（T-b10 弟弟）、judge pass（年青人）、P16-b 组
  （父亲/翠翠的父亲/爹爹）、老船夫/祖父/顺顺 相关（test_role_policy M 组 / test_resolver 全量）。

**真实《边城》重跑（ER_LINEAGE=1，qwen3.7-flash，27/27 chunk 成功）**：
- **B-1 路径真实触发 16 次**：水手/伙计/屠户/脚夫/长年/新嫁娘/大的/小的/卖皮纸的过渡人/那个兵/
  城中人/熟人/顺顺家一个长年/中寨人 等（均 LLM generic 非词表词）→ judge null → skipped_generic
  丢弃（旧行为为 null_registered 碎片化）；persons 32 → 16（与 LLM 方差叠加）。
- **母亲**：本轮 judge 判 resolves_to=女孩子的母亲 → alias（未走 null 路径；图中无独立 母亲 Person，
  `女孩子的母亲.aliases=[白脸黑发小寡妇, 母亲, 妇人, 乡绅女人, 乡绅太太]`）。
- **四历史案例归层无 B-1 回归**（B-1 仅影响 effective-generic + judge-null；四案例本轮路径：
  翠翠的祖父=EXTRACTION_LAYER、岳云二老=ADMISSION_LAYER(target_mismatch, composite 非 generic)、
  弟弟=EXTRACTION_LAYER、爷爷=SUCCESS(→老人)；与上一轮差异均为 LLM 方差，非 B-1 行为）。

**验收结论**：D5-b / B-1 验收通过。A-1（D5-a）作为独立 prompt A/B 实验进入下一阶段（固定模型/温度/
并发/EPUB/chunking/resolver，仅改 prompt，对比 extraction coverage / category / downstream ER /
false-positive regression），单独提交，不与 D5-b 合并。

---

## 附录：v1（2026-08-27，已被 v2 取代；保留历史，不覆盖）

> 以下为 v1 全文。v1 的「爸爸 category=None/PERSON」与「翠翠的祖父 归 P06」假设已被 §0 修正；
> v1 候选方案 A（prompt 增强）/ B（结构补标）/ C（保持现状）/ D（二段式）在 v2 中对应
> A-1 / （未保留：结构补标依赖 category=None 前提，v2 无直接案例，移出本轮）/ B-3 / A-3。

### v1 原文

# Task B：P017 D5 问题边界与候选方案 — extraction classification coverage

- **日期**: 2026-08-27
- **版本**: v1（设计，未实现）
- **状态**: 设计评审中（**只做问题定位与方案设计，不直接修改 P16-b / resolver / hygiene / prompt**）
- **背景**: V0.2.6 验收确认 P017 D5 缺口：`爸爸`（category=None/PERSON）绕过 role admission evidence gate → 未 confirmed 顺顺，反而碎片化为独立 Person（mc=1）；`母亲` 同型（与 V0.2.5 行为一致）。P16-b 本身冻结，此问题单独立项。
- **前置**: V0.2.6 验收报告 §2.3/§5/§10；P018 Follow-up Task B；AGENTS.md §15「不引入 classifier 绕过 P017 D5」「不把 父亲/母亲/祖父 加入 generic 词表」。

## 1. 问题边界（What is / What is not）

### 1.1 症状（V0.2.6 实证）

| mention | extraction category（推断） | 实际行为 | 期望行为 |
|---|---|---|---|
| 爸爸 | None/PERSON（推断：未触发 gate） | 独立 Person（mc=1, ch5） | confirmed 顺顺 alias |
| 爹爹 | DESCRIPTIVE（推断：触发 gate） | confirmed 顺顺 alias ✅ | ✅ |
| 母亲 | None/PERSON（推断） | 独立 Person（mc=6） | （V0.2.5 同行为，历史一致） |
| 父亲 | DESCRIPTIVE（推断：触发 gate） | 不入图、非 Person ✅ | ✅ |

**推断依据**（链路未落盘，为推断非直接观测——Task A 将提供直接证据）：`爸爸` 若 category=DESCRIPTIVE，chunk5/ch6 同文本重叠即可凑 2 独立证据 → 必然 confirmed；但最终是独立 Person → 说明走了 `category=None/PERSON → judge null → 注册 canonical` 路径（`_register_or_unresolved` 的 D4/D5 分支）。

### 1.2 根因层（已锁定，非 gate 逻辑）

- **根因在 extraction classification 层**：LLM 对裸长辈称谓的 category 标注不稳定/缺失（`爸爸` 未标 DESCRIPTIVE；`爹爹` 标了）。
- **放大因素**：`category=None → legacy PERSON fallback → 立即注册 canonical`（`_resolve_name` 无候选分支 / `_register_or_unresolved`）——这是 P017 已记录的 D5 Known Limitation 的**同一机制**（ch5b 一族 长子/次子/第二个儿子 同型）。
- **不是**：P16-b gate 行为错误（gate 在 category=DESCRIPTIVE 时工作正常：爹爹 confirmed、父亲 blocked/unresolved、翠翠的父亲 拦截）。

### 1.3 边界（不做什么）

| 不做 | 原因 |
|---|---|
| 不把 爸爸/母亲/父亲 加入 generic 词表或 hard filter | P16 Do Not Reopen；破坏合法正向吸收（爸爸→顺顺 语义正确） |
| 不给 P16-b 加「爸爸 特殊规则」 | P16-b 冻结；单点补丁掩盖系统问题 |
| 不引入 ML classifier | AGENTS.md §15 锁定；D5 走 P06 follow-up |
| 不直接改 extraction prompt 而不做对照 | prompt 变更影响全部 extraction，需 A/B 验证（可作为候选方案之一，见 §3） |
| 不把「category=None 一律视为 DESCRIPTIVE」 | 会扩大 gate 触发面，误伤 老船夫 等 descriptive epithet（category=PERSON 是保护） |

## 2. 问题定位步骤（实施前必须先做）

1. **Task A 先行**：`ER_LINEAGE=1` 跑《边城》真实 ingest，收集 `extraction_category` 事实 → 量化「裸长辈称谓中 category=None / PERSON / DESCRIPTIVE 的真实分布」。**这是决策依据**——当前所有「爸爸=None/PERSON」均为推断。
2. **对照 extraction_raw**：核对 LLM 是否输出 category 字段（缺失 vs 错标 vs 正确标注）。
3. **按 mention 聚类**：`爸爸`/`爹爹`/`父亲`/`母亲`/`妈妈`/`娘` 各自的 category 分布 + 是否触发 gate + 最终状态 → 建立「category 覆盖缺口清单」。
4. **区分两类缺口**：
   - (a) **标注缺失**（LLM 干脆不输出 category 字段）→ 可能 prompt 指示不足。
   - (b) **标注错误**（输出了但错标 PERSON/None）→ 模型对「描述性称谓」的语义理解问题。
   - 两类修复路径不同（见 §3），必须先区分。

## 3. 候选解决方案（按侵入性排序，均需独立评审）

### 方案 A：extraction prompt 增强（category 示例细化）—— 改动最小面，效果待 A/B

- **做法**：在 `EXTRACTION_SYSTEM_PROMPT` 的 category 定义中，为 DESCRIPTIVE 增加「裸长辈称谓」（爸爸/爹爹/父亲 指向具体人物时）与「限定式」（翠翠的祖父）的示例；明确「无法确定时省略」的语义边界。
- **优点**：不动判定逻辑；直接改善源头标注；可回滚。
- **风险/代价**：prompt 变更影响**全部** extraction（可能改变其他 category 分布）；需要同一 novel 两次 ingest A/B（原 prompt vs 新 prompt）对比 category 分布与最终 canonical 质量。
- **验证**：A/B 后检查 `爸爸` 是否获得 DESCRIPTIVE 标注且 confirmed；`老船夫` 等 epithet 是否仍 PERSON（不误伤）。

### 方案 B：确定性结构补标（hygiene 层旁路，非 classifier）—— 需明确评审「是否违反 AGENTS.md」

- **做法**：对「**LLM category 缺失（None）** 且 **结构可判定为限定式/长辈裸词**」的 mention，用确定性规则（复用 `classify_role_mention` 的 X的Y 正则 + 长辈首字集，**不新增词表**）在 resolver 内补一个「hygiene 建议 category=DESCRIPTIVE」用于 gate 触发判定（不改 extraction 输出本身）。
- **优点**：不依赖 LLM 标注；确定性；可单测。
- **风险**：① 与 AGENTS.md「不引入 classifier 绕过 P017 D5」的边界——**结构规则 ≠ classifier**（无学习、纯模式匹配），但需评审确认；② 扩大 gate 触发面（老船夫 首字"老"∉ 长辈首字集，天然排除 ✓；但 母亲 等会进 gate——需评估）；③ `PERSON` 标注的裸词是否也补标（爸爸 若是 PERSON 而非 None，补标范围不同）。
- **验证**：unit 增补「category=None 长辈裸词 → 补标 DESCRIPTIVE → 触发 gate」矩阵；真实评估确认 爸爸 confirmed 且 老船夫 路径零变化。

### 方案 C：保持现状 + Known Limitation 文档化（零代码）

- **做法**：不修；在 P017/P018 记录 D5 为 Accepted Limitation；用 Task A 数据持续量化。
- **适用**：如果 Task A 显示 category=None 占比低（<10% 且仅个别词），或 A/B 显示 prompt 增强无法稳定改善。
- **代价**：爸爸 类合法 alias 持续漏配（信息损失，与 P16-b「首次信息损失」trade-off 一致）。

### 方案 D（远期，不推荐本轮）：二段式 extraction

- 对 category=None 的裸长辈称谓做第二次 LLM 询问（补 category）——**增加 LLM 调用**，与「零额外调用」原则冲突，仅记录为远期选项。

## 4. 推荐路径（决策建议）

```text
Step 1  Task A lineage 上线 → 真实评估量化 category 缺口（区分缺失 vs 错标）   [前置，必做]
Step 2  若缺口集中在「标注缺失」→ 方案 A（prompt 增强）+ A/B 对照            [低风险优先]
Step 3  若 A/B 无效或缺口在「错标」→ 方案 B（结构补标）立项评审                [需 AGENTS.md 边界确认]
Step 4  若缺口占比低 / 修复成本高 → 方案 C（Accepted Limitation + 文档化）
```

**明确**：本任务**不实施任何方案**；本轮交付 = 问题边界 + 候选方案 + 决策路径，供评审后另立项。

## 5. 验收（实施后）

- 方案 A/B 任一落地后：`爸爸 → 顺顺` confirmed 恢复；`老船夫 → 祖父` 路径不变；`母亲` 行为有明确定论（confirmed 或 Accepted Limitation）；unit + integration 全绿；V0.2.6 已验收的 父亲拦截 / 翠翠的父亲拦截 / 顺顺 sink 不回归。

## 6. Do Not

- 不修改 P16-b gate（冻结）。
- 不引入 classifier / 不扩词表 / 不把 category=None 一刀切当 DESCRIPTIVE。
- 不把单次真实评估的 category 推断当事实（先上 Task A 拿直接证据）。

### （v1 原文结束）
