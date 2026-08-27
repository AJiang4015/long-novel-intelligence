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
