# V0.2.6：P16-b 正文 relational-role alias 准入策略 — 设计文档

- **日期**: 2026-08-26
- **版本**: V0.2.6（P16-b 专项，候选 A+B 细化）
- **状态**: 设计评审中（未实现，不改任何代码）
- **前置**: V0.2.5 封版（P16-a PASS / P17 PARTIAL / merge INCONCLUSIVE）；P018 诊断报告已确认机制
- **相关**: [P018 记录](docs/problems/P018-relational-role-canonical-sink.md) / [V0.2.5 评估报告](docs/evaluation/2026-08-26-biancheng-v025-eval.md)

## 1. 背景与问题（诊断结论引用）

P16-b 根因（P018 诊断 + mock 实证）：**judge 层的 `resolves_to` 被无条件接受**——relational-role mention 与任一 canonical 同 chunk 共现即产生候选，judge 误判（或弱上下文）即错吸进 canonical sink（M5 实证：`翠翠的父亲` 仅与顺顺共现 → judge 误判 → 错吸）。

关键事实：
- `父亲` 在《边城》正文指向 **≥3 个不同人物**（顺顺 / 翠翠之父 / 老船夫）+ 题记 1 实体——**跨人物裸 role**，不应 sink 到任何单一 canonical。
- `爸爸`（ch5/6/14/22 → 顺顺）、`爹爹`（ch13/20 → 顺顺）——**人物专属裸 role**，合法 alias。
- `翠翠的祖父`（单次，ch10）→ 祖父 合法 alias（T-b8 锁死）；`翠翠的父亲`（ch16/24）→ judge null → unresolved（现有兜底正确）。
- `哥哥`→大老、`弟弟`→二老 为 **GENERIC（RC3 词表）**，保持 RC3「有候选可 alias」语义，**本设计不触碰**。

## 2. 设计目标与边界

**目标**：当 relational-role mention 指向不明确时，alias 注册需要**证据确认**；区分「角色称谓正确归属」与「跨人物错误吸收」。

**必须保持**（安全基线）：
- 爸爸/爹爹 → 顺顺、哥哥 → 大老、弟弟 → 二老：合法 alias 最终建立。
- 翠翠的祖父 → 祖父：单次合法 alias（T-b8）。
- canonical-first-seen 规则、PERSON 无候选注册、P16-a provisional、P17 deferred/unresolved、RC2/RC3、GENERIC 语义、judge 契约、prompt、merge bridge、Neo4j schema：**全部不变**。
- judge 每 chunk 至多一次（零额外 LLM 调用）；证据机制用确定性计数。

**不触碰**：hygiene.py 词表（父亲/爸爸/爹爹 绝不加入 GENERIC）、DESCRIPTIVE deferred 规则（P17）、`_resolve_name` 的 PERSON/None 分支。

## 3. 核心概念：RoleMention 形态判定（确定性结构规则，非词表）

`classify_role_mention(name) -> (kind, anchor)`，运行时可访问 resolver `known`：

| kind | 判定规则（按优先级） | anchor | 例 |
|---|---|---|---|
| `qualified` | ① 形如 `X的Y`（正则 `^(.{1,4})的(.{1,8})$`，X 非空） | X（若 X ∈ known 则有效；否则 anchor=None） | 翠翠的父亲 → 翠翠；翠翠的祖父 → 翠翠 |
| `qualified` | ② 复合称谓：name 长度 ≥2 且包含任一 known canonical/alias 名作为子串 | 最长已知名子串 | 天保大老 → 天保；岳云二老 → 岳云（若 known）；翠翠祖父 → 翠翠 |
| `bare` | 其余（无锚点结构的纯角色词） | None | 父亲/爸爸/爹爹/祖父/母亲/老船夫… |

**特殊规则**：
- RC3 GENERIC（哥哥/弟弟/儿子/女儿/妻子/丈夫…）：**不进入本机制**（保持 RC3「有候选可 alias」）。
- `bare` 且为已知 canonical 本身（祖父/母亲）：不触发证据门槛（它们是 canonical 主名，其吸收路径不受影响——`_add_alias` 只作用于 alias 侧）。

## 4. 证据机制（observation / confirmed / conflict）

resolver 新增状态（整本持续，chunk 级写入）：

```python
_role_observations: dict[str, dict[str, set[int]]]  # mention -> {canonical -> {chunk_id}}
_role_confirmed:   set[tuple[str, str]]             # (mention, canonical) 已确认
_role_conflicts:   dict[str, int]                   # mention -> 跨人物冲突信号计数
```

**判定状态机**（仅作用于「judge 判定 `resolves_to=C` 的 role mention」，按 §5 分派）：

```
judge 判 mention -> C
    │
    ├─ (mention, C) ∈ _role_confirmed ──────────────→ 正常 alias（现有 _add_alias 路径）
    │
    ├─ qualified 且 anchor ∈ 候选集 ────────────────→ 正常 alias（现有路径，单次即可）
    │
    ├─ qualified 且 anchor 有效但 ∉ 候选集 ──────────→ observation（需二次证据）
    │
    ├─ qualified 且 anchor 无效（X 非 known）─────────→ 按 bare 处理
    │
    └─ bare ────────────────────────────────────────→ observation（需二次证据）

observation 记录：_role_observations[mention][C].add(chunk_id)
    ├─ |独立证据| >= 2（跨 chunk 去重）→ confirmed：_add_alias(C, mention)；移除 observation；输出正常归并
    └─ < 2 → 本 chunk 该 mention 从 resolved 输出剔除（不注册、不 alias、不建 Person）

冲突信号（judge null / missing / exception 路径）：
    若 mention 曾有 observation 或 confirmed → _role_conflicts[mention] += 1
    （null/missing 走现有 unresolved；exception 走现有 D4 分派——本设计不改变这些路径本身）

全书末兜底（novels.py 在 apply_aliases 之前调用 resolver.finalize_role_confirmations()）：
    对 observation 中 (mention, C) 且 _role_conflicts[mention] == 0 → 确认 alias（防信息损失）
    有冲突 → 保持未确认（mention 不入图）
```

## 5. 判定规则详表（评审必答点）

| # | 设计点 | 规则 |
|---|---|---|
| 1 | 裸/限定判定 | §3 结构规则（X的Y / 复合称谓子串 / 其余 bare）；不引入词表，不改 hygiene.py |
| 2 | observation/confirmed 状态 | §4 状态机；observation 期输出剔除；confirmed 后正常 alias |
| 3 | ≥2 次独立证据定义 | **独立证据 = (mention→C) 由 judge 判定且 chunk_id 不同**（跨 chunk 去重）；同 chunk 多 mention 实例只计 1 次；**跨 chapter 证据更佳但非必需**（ch5b + ch14 = 2 独立证据）；同上下文重复（M6）不算 |
| 4 | single-candidate | bare 一律证据门槛（候选数无关）；qualified 且 anchor ∉ 候选集 → observation（single-candidate 高风险场景覆盖） |
| 5 | 多 candidate | **保持当前 judge 路径**（M4 实证 judge 多候选可正确区分）；judge 判 C → 仍按 §4 分派（bare 需证据） |
| 6 | judge null/missing/exception | 现有路径不变（null/missing → unresolved；exception → D4 分派）；同时累计冲突信号（供兜底与诊断） |
| 7 | 确认后是否继续累计证据 | **不累计**（confirmed 后 known 命中直接 alias）；冲突信号继续记录（仅诊断，不自动撤销——避免不稳定） |
| 8 | 是否允许跨 chapter 累积 | **允许**（证据按 chunk_id 去重，跨 chapter 自然成立）；同 chapter 不同 chunk（超长章切块）也有效 |
| 9 | canonical-first-seen 保持 | 不触碰 `_register`/`_first_seen`；role mention 永不因本机制注册 canonical（observation 期剔除） |
| 10 | 合法 alias 保证 | 爸爸（ch5/6/14/22 ≥2 证据）/ 爹爹（ch13/20 ≥2 证据）→ confirmed ✓；**父亲 因跨人物证据（ch16/24 null）有冲突 → 正确地不建立 alias（防 sink）**——这是 P16-b 目标，不是缺陷 |

## 6. 输出与图构建行为

- observation 期（未确认）：该 chunk 的 role mention **从 resolved 输出剔除**（类似 unresolved 剔除路径，复用 dropped 集合机制）。
- confirmed 后：mention 正常解析为 canonical（known 命中），aliases 含该 mention。
- 全书末兜底确认发生在 `merge_extractions` 之后、`apply_aliases` 之前（novels.py 新增一行调用）——确保兜底确认的 alias 进入图。
- `finalize()`（-a provisional flush）不变；`finalize_role_confirmations()` 为新增独立方法。

## 7. 测试矩阵（deterministic，mock judge，复用 T-b 基础设施）

| ID | 场景 | 期望 |
|---|---|---|
| M1 | 单次合法 父亲 → 顺顺（1 chunk，候选 [顺顺]） | **不立即 alias**；observation；输出剔除；无 父亲 Person/alias |
| M2 | 两次不同 chunk 合法证据（ch1 + ch2 各判 父亲→顺顺） | 第二次触发 confirmed → alias 顺顺；输出归并 |
| M4 | 多候选 role（父亲 候选 [祖父,顺顺]，judge 判 祖父） | 保持 judge 路径；observation→祖父（需二次证据确认） |
| M5 | 单候选错误（翠翠的父亲 候选 [顺顺]，judge 误判 顺顺；锚点 翠翠 known 且 ∉ 候选） | **不得 alias**；observation（锚点 ∉ 候选集）→ 不确认 → 不入图 |
| M6 | 同一错误上下文重复两次（同 chunk 两处 翠翠的父亲→顺顺） | 证据按 chunk 去重 = 1 → 不 alias |
| M7 | 限定 + 裸混合（同 chunk：翠翠的父亲 + 父亲，judge 判 顺顺 + 顺顺） | 翠翠的父亲 → observation（锚点 翠翠 ∉ 候选）；父亲 → observation；互不干扰 |
| M8 | 已确认 alias 回归（爸爸→顺顺 confirmed 后，ch3 再出现 爸爸→顺顺） | 直接 alias（不重复累计、不再剔除） |
| M9 | 翠翠的祖父（候选含 祖父 + 锚点 翠翠 ∈ 候选，judge 判 祖父） | **单次 alias 保持**（T-b8 回归） |
| M10 | 哥哥→大老（GENERIC） | RC3 路径不变（不触发证据门槛） |
| M11 | 兜底确认（父亲→顺顺 全书仅 1 证据、无冲突） | finalize_role_confirmations → alias |
| M12 | 兜底不确认（父亲→顺顺 1 证据 + 翠翠的父亲 null 冲突） | 有冲突 → 不确认 → 不入图 |

**回归**：T-a 全量（P16-a）、T-b 全量（P17，**deferred/unresolved 行为必须零变化**）、test_hygiene（RC2/RC3）、test_resolver（既有 alias 路径）、integration 15。

## 8. Trade-offs

- **首次信息损失**：bare role 首次（observation 期）mention 从输出剔除；若全书仅 1 次且无冲突 → 兜底确认时**历史 chunk 无法追溯**（图缺失该次 mention 计数）。对《边城》：父亲 本就不入图（正确）；爸爸/爹爹 首次出现剔除但后续确认。
- **父亲 不 alias 顺顺**：跨人物裸 role 不 sink 是 P16-b 目标；代价是「作父亲的」不再归入顺顺（图面信息降级，语义正确性优先）。
- **证据门槛依赖 judge 初次判定正确**：observation 记录的是 judge 判定（可能初次就错）——但 M5 场景（锚点 ∉ 候选）被 observation 拦截；初次判定错 + 两次独立错误证据（M6 同上下文不算）才可能错确认——风险显著低于现状无条件接受。
- **GENERIC 例外**：哥哥/弟弟 保持单次 alias（RC3 锁），依赖其专属性强；若未来出现跨人物 GENERIC，需另议。
- 零额外 LLM 调用；确定性计数成本可忽略。

## 9. 不变量 / Do Not Do

- 不修改 hygiene.py、RC2/RC3、P16-a（section/provisional）、P17（deferred/unresolved）、P017 D5、merge bridge、judge 契约、prompt、Neo4j schema、并发/超时。
- 不把 父亲/爸爸/爹爹/任何 role 词加入 GENERIC 或 hard filter。
- 不改 `_resolve_name` 的 PERSON/None 分支；不改 `_register`/`_first_seen`。
- judge 每 chunk 至多一次；证据机制零额外 LLM 成本。
- observation/conflict 状态只增不改历史（已确认 alias 不自动撤销；冲突仅计数）。

## 10. 后续

- 实现前以 M1/M2/M4/M5/M6/M7/M8 固化当前行为基线（先写测试，全红 → 实现 → 全绿）。
- 端到端接入点：novels.py `finalize_role_confirmations()` 调用（apply_aliases 前）。
- Group 模型 / 关系角色建模：留待未来（P16-b 不引入）。
