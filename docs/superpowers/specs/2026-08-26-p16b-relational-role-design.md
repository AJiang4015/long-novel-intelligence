# V0.2.6：P16-b 正文 relational-role alias 准入策略 — 设计文档（修订版 v4）

- **日期**: 2026-08-26（v4 修订：qualified 安全路径改为「核词/anchor 对齐」判据，anchor ∈ candidates 不再作为安全依据，关闭 M17）
- **版本**: V0.2.6（P16-b 专项，候选 A+B 细化，评审修订 v4）
- **状态**: 设计评审中（未实现，不改任何代码）
- **前置**: V0.2.5 封版（P16-a PASS / P17 PARTIAL / merge INCONCLUSIVE）；P018 诊断报告已确认机制
- **相关**: [P018 记录](docs/problems/P018-relational-role-canonical-sink.md) / [V0.2.5 评估报告](docs/evaluation/2026-08-26-biancheng-v025-eval.md)

## 1. 背景与问题（诊断结论引用）

P16-b 根因（P018 诊断 + mock 实证）：**judge 层的 `resolves_to` 被无条件接受**——relational-role mention 与任一 canonical 同 chunk 共现即产生候选，judge 误判（或弱上下文）即错吸进 canonical sink（M5 实证：`翠翠的父亲` 仅与顺顺共现 → judge 误判 → 错吸）。

关键事实：
- `父亲` 在《边城》正文指向 **≥3 个不同人物**（顺顺 / 翠翠之父 / 老船夫）+ 题记 1 实体——**跨人物裸 role**，不应 sink 到任何单一 canonical。
- `爸爸`（ch5/6/14/22 → 顺顺）、`爹爹`（ch13/20 → 顺顺）——**人物专属裸 role**，合法 alias（需 ≥2 独立证据确认）。
- `翠翠的祖父`（单次，ch10）→ 祖父 合法 alias（T-b8 锁死）；`翠翠的父亲`（ch16/24）→ judge null → unresolved（现有兜底正确）。
- `哥哥`→大老、`弟弟`→二老 为 **GENERIC（RC3 词表）**，保持 RC3「有候选可 alias」语义，**本设计不触碰**。
- `老船夫`/`撑渡船的老头子` 等是 **descriptive epithet**（高频人物称谓，非 relational-role），**不进本机制**（见 §3 触发条件）。

## 2. 设计目标与边界

**目标**：当 relational-role mention 指向不明确时，alias 注册需要**证据确认**；区分「角色称谓正确归属」与「跨人物错误吸收」。**核心不变式（v4）**：
1. <2 次独立证据的 bare alias 永不成立（无任何自动晋升路径，含全书末）；
2. **qualified 的判定可确认性以「target 对齐」为前提**——judge 判定的 C 必须与 mention 的**核词或 anchor 对齐**，否则（target-mismatch）永不确定；anchor ∈ candidates 只说明锚点可参与判定，**不构成安全依据**（M17 反例）；
3. alias 只来自两条路径：(a) judge 判定 + target 对齐 + anchor 在场（qualified 安全路径）；(b) bare 的 ≥2 跨 chunk 独立证据。无第三条路径。

**必须保持**（安全基线）：
- 爸爸/爹爹 → 顺顺、哥哥 → 大老、弟弟 → 二老：合法 alias 最终建立。
- 翠翠的祖父 → 祖父：单次合法 alias（T-b8）。
- 老船夫 → 祖父：descriptive epithet 的现有 alias 路径（不进证据机制）。
- canonical-first-seen、PERSON 无候选注册、P16-a provisional、P17 deferred/unresolved、RC2/RC3、GENERIC 语义、judge 契约、prompt、merge bridge、Neo4j schema：**全部不变**。
- judge 每 chunk 至多一次（零额外 LLM 调用）；证据机制用确定性计数。

**不触碰**：hygiene.py 词表（父亲/爸爸/爹爹 绝不加入 GENERIC）、DESCRIPTIVE deferred 规则（P17）、`_resolve_name` 的 PERSON/None 分支。

## 3. RoleMention 分类与触发条件

### 3.1 形态判定与核词提取（确定性结构规则，非词表）

`classify_role_mention(name) -> (kind, anchor, headword)`，运行时可访问 resolver `known`：

| kind | 判定规则（按优先级） | anchor | 核词 headword | 例 |
|---|---|---|---|---|
| `qualified` | ① `X的Y`（正则 `^(.{1,4})的(.{1,8})$`，X 非空） | X（若 X ∈ known 则有效；否则 anchor=None） | Y（"的"后全部） | 翠翠的父亲 → anchor 翠翠 / 核词 父亲；翠翠的祖父 → anchor 翠翠 / 核词 祖父 |
| `qualified` | ② 复合称谓：name 长度 ≥2 且包含任一 known canonical/alias 名子串 | 最长 known 名子串 | mention 去掉 anchor 后的剩余部分 | 天保大老 → anchor 天保 / 核词 大老；翠翠祖父 → anchor 翠翠 / 核词 祖父；岳云二老 → anchor 岳云（若 known）/ 核词 二老 |
| `bare` | 其余 | None | None | 父亲/爸爸/爹爹/祖父/母亲/老船夫… |

**target 对齐（v4 核心判据，确定性、零 LLM、无 ontology、无词表）**：
```
aligned(C, anchor, headword) =
    C == anchor 的 canonical            # 复合称谓归入 anchor 自身（天保大老→天保）
    或 C 的 canonical 名 == headword     # 关系限定归入核词人物（翠翠的祖父→祖父、翠翠祖父→祖父）
```
- `翠翠的父亲 → 顺顺`：C=顺顺 ≠ anchor(翠翠) 且 C 名(顺顺) ≠ headword(父亲) → **不对齐**（M17 反例拦截）。
- `翠翠的祖父 → 祖父`：C 名(祖父) == headword(祖父) → 对齐 ✓。
- `天保大老 → 天保`：C == anchor(天保) → 对齐 ✓。

### 3.2 触发条件（证据机制只对「需证据」的 role mention 生效）

**`needs_evidence(mention)` 为 true**，当且仅当**同时满足**：

1. `classify_role_mention(name).kind == bare`（qualified 不走证据机制，走 §4 对齐路径）；
2. `classify_mention(name) != MentionCategory.GENERIC`（RC3 词表词不进本机制）；
3. **LLM category == MentionCategory.DESCRIPTIVE**（仅 LLM 判「描述性称谓」的裸词才触发）。

**明确排除**：
- `老船夫`/`撑渡船的老头子`/`年青人`/`中年人` 等 **descriptive epithet**：LLM 通常判 PERSON/None → **不触发**，保持现有 alias 路径。
- category=None/PERSON 的裸词：**不触发**（与 P17 D5 同哲学，Known Limitation，不引入 classifier）。
- GENERIC（RC3 词表）：不触发。
- COMPOSITE（天保大老/岳云二老 category=composite）：**不触发** bare 证据机制（走 §4 qualified 对齐路径）。

> 触发依赖 LLM category（P06 方差）是**有意取舍**：与 P17 D5 一致，避免引入 classifier；风险记录见 §8。

## 4. 判定状态机（修订版 v4：target 对齐 + anchor 在场双条件）

resolver 新增状态（整本持续，chunk 级写入）：

```python
_role_observations: dict[str, dict[str, set[int]]]  # mention -> {canonical -> {chunk_id}}（仅 bare）
_role_confirmed:   set[tuple[str, str]]             # (mention, canonical) 已确认
_role_blocked:     set[str]                         # 跨 canonical 冲突 → 该 mention 永不 alias
```

```
judge 判 mention -> C（resolves_to 有效）
    │
    ├─ (mention, C) ∈ _role_confirmed ──────────────→ 正常 alias（_add_alias 路径）
    │
    ├─ qualified（anchor 有效）：
    │    ├─ target 对齐（C == anchor 的 canonical 或 C 名 == 核词）
    │    │    ├─ anchor ∈ 候选集 → 正常 alias（安全路径，单次；翠翠的祖父→祖父 / 天保大老→天保）
    │    │    └─ anchor ∉ 候选集 → 不可确认（anchor-mismatch；输出剔除，永不 alias）
    │    └─ target 不对齐 → 不可确认（target-mismatch；输出剔除，永不 alias）
    │         —— M17（anchor 在场但 judge 选错 candidate）、M5/M16 均由本条覆盖
    │
    ├─ qualified 且 anchor 无效（X 非 known）─────────→ 按 bare 处理（若 category=DESCRIPTIVE 走证据路径）
    │
    └─ bare（category=DESCRIPTIVE、非 GENERIC）───→ 证据路径：
        ├─ mention ∈ _role_blocked → 输出剔除；不 alias、不累计
        ├─ 已有 observation 指向 C' ≠ C（跨 canonical 冲突）→
        │    _role_blocked.add(mention)；全部 observation 作废；输出剔除
        ├─ 已有 observation 指向 C：
        │    _role_observations[mention][C].add(chunk_id)
        │    ├─ |独立证据| >= 2（不同 chunk_id）且 mention ∉ blocked
        │    │    → confirmed：_add_alias(C, mention)；从 observations 移除
        │    └─ < 2 → 保持 observation；本 chunk 输出剔除
        └─ 无 observation：_role_observations[mention][C] = {chunk_id}；本 chunk 输出剔除

judge null / missing / exception：
    → 现有路径不变（null/missing → unresolved；exception → D4 分派）
    → 不累计 evidence、不触发 observation/blocked、不触发 mismatch

全书末（finalize 阶段）：
    → observation 永不自动晋升；未确认 mention 不入图；无 novels.py 变更
```

**qualified 判定语义（v4）**：
- **anchor 是关系主体，不是关系目标**——`anchor ∈ candidates` 只能说明锚点人物在场、judge 可参考其上下文，**不能证明 C 正确**（M17 反例：翠翠的父亲 候选 [翠翠,顺顺]，anchor 在场但 judge 误判 顺顺）。
- **target 对齐是真正的可测试判据**：C 必须等于 anchor 的 canonical（复合称谓归入自身：天保大老→天保）或 C 名等于核词（关系限定归入核词人物：翠翠的祖父→祖父）。对齐失败 = target-mismatch → 永不确定（不依赖 anchor 在场与否）。
- **anchor 在场是第二重保守条件**：对齐通过但 anchor ∉ 候选集 → 仍不可确认（限定上下文缺失，保守拒绝）。
- **不新增 LLM 调用、无关系 ontology、无大规模 role 词表**：对齐 = 字符串比对 + known 映射（确定性）。

**关键修订（相对 v3）**：
1. v2 已修：无 finalize 自动晋升；跨 canonical 冲突 → blocked。
2. v3 已修：anchor ∉ candidates → 不可确认（M5/M16）。
3. **v4 新增：target 对齐判据**——anchor ∈ candidates 不再构成安全依据；qualified 单次 alias 必须「对齐 + anchor 在场」双条件（M17 关闭）。

## 5. 判定规则详表（评审必答点，v2 修订）

| # | 设计点 | 规则 |
|---|---|---|
| 1 | 裸/限定判定 | §3.1 结构规则；触发另需 §3.2 三条件（bare/qualified 高风险 + 非 GENERIC + LLM DESCRIPTIVE） |
| 2 | observation/confirmed 状态 | §4 状态机；observation 期输出剔除；**observation 永不自动晋升**；confirmed 后正常 alias |
| 3 | ≥2 独立证据定义 | **工程级定义：独立证据 = (mention→C) 由 judge 判定且 chunk_id 不同**（跨 chunk 去重）。**明确记录：这是工程级近似，不是语义独立性保证**——同 chunk 内多次 mention 实例因 judge 批处理只判一次而只计 1 个证据；宁可漏确认（保守）不可错确认。跨 chapter 证据自然满足 |
| 4 | single-candidate / qualified 判定 | bare 一律证据门槛；**qualified 单次 alias 需「target 对齐 + anchor 在场」双条件**——anchor ∈ candidates 不构成安全依据（M17）；target 不对齐或 anchor 缺席 → 不可确认 |
| 5 | 多 candidate | 保持当前 judge 路径（M4 实证）；judge 判 C → 按 §4 分派 |
| 6 | judge null/missing/exception | 现有路径不变；**不累计 evidence、不触发 observation/blocked**（null 只是「无法判定」，不充当跨人物证据） |
| 7 | 确认后是否继续累计证据 | 不累计（confirmed 后 known 命中直接 alias）；不自动撤销（稳定性优先） |
| 8 | 是否允许跨 chapter 累积 | 允许（按 chunk_id 去重；跨 chapter 自然成立；同 chapter 不同 chunk 也有效） |
| 9 | canonical-first-seen 保持 | 不触碰 `_register`/`_first_seen`；role mention 永不因本机制注册 canonical（observation 期剔除） |
| 10 | 合法 alias 保证 | 爸爸（ch5/6/14/22 ≥2 证据）/ 爹爹（ch13/20 ≥2 证据）→ confirmed ✓；**父亲 因跨人物（ch16/24 翠翠之父 null + 全书仅 ch5b 1 次顺顺证据）→ 永不确认、不入图**——P16-b 目标（跨人物裸 role 不 sink），非缺陷 |

## 6. 输出与图构建行为

- observation 期（未确认/blocked）：该 chunk 的 role mention **从 resolved 输出剔除**（复用 dropped 集合机制；不注册、不 alias、不建 Person）。
- confirmed 后：mention 正常解析为 canonical（known 命中），aliases 含该 mention。
- **无 novels.py 变更**（v1 的 `finalize_role_confirmations()` 调用删除）；`finalize()`（-a provisional flush）不变。

## 7. 测试矩阵（deterministic，mock judge，复用 T-b 基础设施）

| ID | 场景 | 期望 |
|---|---|---|
| M1 | 单次合法 父亲→顺顺（DESCRIPTIVE bare，1 chunk） | **不 alias**；observation；输出剔除；**全书末仍保持 observation**（无任何路径晋升） |
| M2 | 两次不同 chunk 合法证据（ch1+ch2 判 父亲→顺顺） | 第二次触发 confirmed → alias 顺顺；输出归并 |
| M4 | 多候选 role（父亲 候选 [祖父,顺顺]，judge 判 祖父） | 保持 judge 路径；observation→祖父（需 ≥2 证据确认） |
| M5 | 单候选错误（翠翠的父亲 anchor 翠翠 ∉ 候选 [顺顺]，judge 误判 顺顺） | **不可确认**（anchor-mismatch + target-mismatch）：不记 observation、不入图；永不 alias |
| M6 | 同一错误上下文重复两次（同 chunk 两处 翠翠的父亲→顺顺） | 证据按 chunk 去重 = 1 → 不 alias |
| M7 | 限定 + 裸混合（同 chunk：翠翠的父亲 + 父亲，judge 均判 顺顺） | 翠翠的父亲：target 不对齐 → 不可确认；父亲（bare）→ observation；互不干扰 |
| M8 | 已确认 alias 回归（爸爸→顺顺 confirmed 后，ch3 再出现） | 直接 alias（不重复累计、不剔除） |
| M9 | 翠翠的祖父（anchor 翠翠 ∈ 候选 [翠翠,祖父]，核词 祖父 == C 祖父） | **单次 alias 保持**——依据：target 对齐（C 名==核词）+ anchor 在场；T-b8 回归 |
| M10 | 哥哥→大老（GENERIC） | RC3 路径不变（不触发证据机制） |
| M11（重定义） | **1 evidence + 无 conflict → 全书末保持 observation**（显式验证 gate 不被绕过） | 不确认；mention 不入图 |
| M12（重定义） | **跨 canonical 冲突**：父亲（bare）ch1 判→顺顺、ch2 判→祖父 | blocked；父亲 全部 observation 作废；永不确定；不入图 |
| M13（新增） | 跨 canonical 冲突变体：同一 bare mention 两 canonical 各 1 证据 | blocked（不允许分别累计独立确认） |
| M14 | 老船夫→祖父（descriptive epithet，LLM category=PERSON） | **不触发证据机制**；保持现有单次 alias 路径 |
| M15 | 父亲（LLM category=None → PERSON fallback） | 不触发（D5 一致 Known Limitation）；保持现状 |
| M16 | 同一 qualified role（翠翠的父亲）anchor 连续缺席候选、两个不同 chunk 均错误 resolves_to 同一 C（顺顺） | **必须不确认**：每次判定均 anchor-mismatch → 不入 observation → 永无 ≥2 证据 → 不入图 |
| **M17（新增）** | **qualified anchor ∈ candidates，但 judge 错误选择另一 candidate**：翠翠的父亲，candidates=[翠翠,顺顺]，judge→顺顺 | **必须不确认**：target 不对齐（C=顺顺 ≠ anchor 翠翠，C 名≠核词 父亲）→ target-mismatch 不可确认 → 不入图（v3 的「anchor ∈ candidates → 安全 alias」被本条证伪并关闭） |

**回归**：T-a 全量（P16-a）、T-b 全量（P17，deferred/unresolved 行为零变化）、test_hygiene（RC2/RC3）、test_resolver（既有 alias 路径）、integration 15。

## 8. Trade-offs（v4 修订）

- **首次信息损失（无兜底补偿）**：bare role 首次 mention 输出剔除；若全书仅 1 次证据 → 永久不入图（父亲 场景）。「错确认防 sink」优先（v2/v3/v4 均无 finalize 兜底）。
- **父亲 不 alias 顺顺**：跨人物裸 role 不 sink（P16-b 核心目标）；「作父亲的」不入图。
- **qualified 核词对齐的取舍**：
  - 合法场景保持：翠翠的祖父→祖父（核词对齐）、天保大老→天保（anchor 对齐）、翠翠祖父→祖父（核词对齐）。
  - 潜在漏配：若限定 mention 的 canonical 以全名命名（如「翠翠父亲」而非核词「祖父」），核词对齐会拒绝合法 alias——trade-off 接受（《边城》无此场景；保守防错优先）。
  - **M17 关闭代价**：anchor ∈ candidates 不再直接放行——judge 必须判到对齐目标才单次 alias。
- **触发依赖 LLM category（D5 同哲学）**：category=None/PERSON 的裸词不触发（父亲 若被标 PERSON 则保持现状 judge 吸收）——与 P17 D5 一致的 Known Limitation，**不引入 classifier**；若实测覆盖不足，走 P06 follow-up。
- **descriptive epithet 保护**：老船夫 类不进机制（category=PERSON）→ 现有 alias 路径零变化。
- **GENERIC/COMPOSITE 例外**：哥哥/弟弟（GENERIC）、天保大老/岳云二老（COMPOSITE）不进 bare 证据机制——分别走 RC3 语义与 §4 对齐路径。
- 零额外 LLM 调用；对齐与证据均为确定性字符串/known 操作，成本可忽略。

## 9. 不变量 / Do Not Do

- 不修改 hygiene.py、RC2/RC3、P16-a（section/provisional）、P17（deferred/unresolved）、P017 D5、merge bridge、judge 契约、prompt、Neo4j schema、并发/超时。
- 不把 父亲/爸爸/爹爹/任何 role 词加入 GENERIC 或 hard filter。
- **observation 永不自动晋升**（不存在 finalize/末次兜底路径）。
- 不改 `_resolve_name` 的 PERSON/None 分支；不改 `_register`/`_first_seen`。
- judge 每 chunk 至多一次；证据机制零额外 LLM 成本。
- 已确认 alias 不自动撤销；跨 canonical 冲突 → blocked（只增不改）。

## 10. 后续

- 实现前以 M1-M17 固化当前行为基线（先写测试，全红 → 实现 → 全绿）。
- 实现范围：resolver 新增 `_role_observations/_role_confirmed/_role_blocked` + `classify_role_mention`（含核词提取）+ target 对齐 + anchor 在场判定 + evidence 分派；**无 novels.py 变更**。
- 若真实评估显示 LLM category 覆盖不足（父亲 被标 PERSON 未触发）→ 走 P06 follow-up（category 质量），不擅自扩触发范围。
- Group / 关系角色建模：留待未来（P16-b 不引入）。
