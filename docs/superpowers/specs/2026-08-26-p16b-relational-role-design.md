# V0.2.6：P16-b 正文 relational-role alias 准入策略 — 设计文档（修订版 v3）

- **日期**: 2026-08-26（v3 修订：补齐 qualified anchor-mismatch 语义，关闭 M16 跨 chunk 重复误判 confirmed 漏洞）
- **版本**: V0.2.6（P16-b 专项，候选 A+B 细化，评审修订 v3）
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

**目标**：当 relational-role mention 指向不明确时，alias 注册需要**证据确认**；区分「角色称谓正确归属」与「跨人物错误吸收」。**核心不变式（v3）**：
1. <2 次独立证据的 bare alias 永不成立（无任何自动晋升路径，含全书末）；
2. **qualified 的判定可确认性以「锚点在场」为前提**——anchor-mismatch（锚点 ∉ 候选集）的判定永不确定，重复出现不构成独立证据。

**必须保持**（安全基线）：
- 爸爸/爹爹 → 顺顺、哥哥 → 大老、弟弟 → 二老：合法 alias 最终建立。
- 翠翠的祖父 → 祖父：单次合法 alias（T-b8）。
- 老船夫 → 祖父：descriptive epithet 的现有 alias 路径（不进证据机制）。
- canonical-first-seen、PERSON 无候选注册、P16-a provisional、P17 deferred/unresolved、RC2/RC3、GENERIC 语义、judge 契约、prompt、merge bridge、Neo4j schema：**全部不变**。
- judge 每 chunk 至多一次（零额外 LLM 调用）；证据机制用确定性计数。

**不触碰**：hygiene.py 词表（父亲/爸爸/爹爹 绝不加入 GENERIC）、DESCRIPTIVE deferred 规则（P17）、`_resolve_name` 的 PERSON/None 分支。

## 3. RoleMention 分类与触发条件

### 3.1 形态判定（确定性结构规则，非词表）

`classify_role_mention(name) -> (kind, anchor)`，运行时可访问 resolver `known`：

| kind | 判定规则（按优先级） | anchor | 例 |
|---|---|---|---|
| `qualified` | ① `X的Y`（正则 `^(.{1,4})的(.{1,8})$`，X 非空） | X（若 X ∈ known 则有效；否则 anchor=None） | 翠翠的父亲 → 翠翠；翠翠的祖父 → 翠翠 |
| `qualified` | ② 复合称谓：name 长度 ≥2 且包含任一 known canonical/alias 名子串 | 最长已知名子串 | 天保大老 → 天保；翠翠祖父 → 翠翠 |
| `bare` | 其余 | None | 父亲/爸爸/爹爹/祖父/母亲/老船夫… |

### 3.2 触发条件（证据机制只对「需证据」的 role mention 生效）

**`needs_evidence(mention)` 为 true**，当且仅当**同时满足**：

1. `classify_role_mention(name).kind == bare` **或**（qualified 且 anchor 有效但 judge 目标 ∉ 候选集，见 §4）；
2. `classify_mention(name) != MentionCategory.GENERIC`（RC3 词表词不进本机制——哥哥/弟弟/儿子/女儿/妻子/丈夫 保持 RC3「有候选可 alias」）；
3. **LLM category == MentionCategory.DESCRIPTIVE**（resolver `_category_of`；仅 LLM 判为「描述性称谓」的裸词才触发）。

**明确排除**：
- `老船夫`/`撑渡船的老头子`/`年青人`/`中年人` 等 **descriptive epithet**：LLM 通常判 PERSON/None → **不触发**，保持现有 alias 路径（单次可 alias，如 老船夫→祖父）。
- category=None/PERSON 的裸词（如 LLM 把 父亲 标 PERSON）：**不触发**，保持现状（与 P17 D5 同哲学——category 覆盖缺口记录为 Known Limitation，不引入 classifier）。
- GENERIC（RC3 词表）：不触发。
- qualified 且 anchor ∈ 候选集：不触发（安全路径，§4）。

> 触发依赖 LLM category（P06 方差）是**有意取舍**：与 P17 D5 一致（category=None → 不生效），避免引入 classifier；风险记录见 §8。

## 4. 证据状态机（修订版 v3：anchor-mismatch 不可确认）

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
    ├─ qualified 且 anchor 有效 且 anchor ∈ 候选集 ────→ 正常 alias（安全路径，单次；翠翠的祖父→祖父 保持）
    │
    ├─ qualified 且 anchor 有效 且 anchor ∉ 候选集 ────→ 【anchor-mismatch：不可确认】
    │    输出剔除；不记 observation、不累计 evidence、不进 blocked
    │    （M5/M16：无论判定重复多少次，永不 alias）
    │
    ├─ qualified 且 anchor 无效（X 非 known）─────────→ 按 bare 处理（若 category=DESCRIPTIVE 走证据路径）
    │
    └─ bare（且 category=DESCRIPTIVE、非 GENERIC）───→ 证据路径：
        │
        ├─ mention ∈ _role_blocked → 输出剔除；不 alias、不累计
        │
        ├─ 已有 observation 指向 C' ≠ C（跨 canonical 冲突）→
        │    _role_blocked.add(mention)；该 mention 全部 observation 作废；输出剔除
        │
        ├─ 已有 observation 指向 C：
        │    _role_observations[mention][C].add(chunk_id)
        │    ├─ |独立证据| >= 2（不同 chunk_id）且 mention ∉ blocked
        │    │    → confirmed：_add_alias(C, mention)；从 observations 移除
        │    └─ < 2 → 保持 observation；本 chunk 输出剔除
        │
        └─ 无 observation：_role_observations[mention][C] = {chunk_id}；本 chunk 输出剔除

judge null / missing / exception：
    → 现有路径不变（null/missing → unresolved；exception → D4 分派）
    → 不累计 evidence、不触发 observation/blocked、不触发 anchor-mismatch

全书末（finalize 阶段）：
    → observation 永不自动晋升；未确认 mention 不入图；无 novels.py 变更
```

**anchor-mismatch 语义（v3 新增）**：
- 定义：qualified mention 的 judge 判定 `resolves_to C`，当 **anchor 人物不在候选集**（候选集中无 anchor canonical）时，判定**缺少锚点判别基础**——即使 C 在候选、即使判定在多个 chunk 重复出现，**该判定不可确认**（锚点缺席 = 无独立的判别依据，重复的同类误判不是独立证据）。
- 与 bare 的本质区别：bare 无锚点 → judge 判定是唯一信息，用 ≥2 独立共识确认；qualified 有锚点 → **锚点在场是判定可确认的前提**，锚点缺席的判定（anchor-mismatch）永远不入 evidence 累计。
- **不新增 LLM 调用**：anchor 在场判定 = 锚点 canonical ∈ PendingMention.candidates（确定性检查）。

**关键修订（相对 v2）**：
1. v2 已修：删除全书末自动确认（observation 永不晋升）；跨 canonical 冲突 → blocked。
2. **v3 新增：qualified + anchor 缺席 → 不可确认（不入 observation）**——关闭 M16：同一 qualified role 跨 chunk 重复误判同一 C 不再能凑齐 ≥2 evidence（每次判定都被定义为不可确认）。
3. bare role 的 ≥2 chunk 证据机制**完全不变**（M1/M2/M4/M6/M8/M11/M12/M13 保持）。

## 5. 判定规则详表（评审必答点，v2 修订）

| # | 设计点 | 规则 |
|---|---|---|
| 1 | 裸/限定判定 | §3.1 结构规则；触发另需 §3.2 三条件（bare/qualified 高风险 + 非 GENERIC + LLM DESCRIPTIVE） |
| 2 | observation/confirmed 状态 | §4 状态机；observation 期输出剔除；**observation 永不自动晋升**；confirmed 后正常 alias |
| 3 | ≥2 独立证据定义 | **工程级定义：独立证据 = (mention→C) 由 judge 判定且 chunk_id 不同**（跨 chunk 去重）。**明确记录：这是工程级近似，不是语义独立性保证**——同 chunk 内多次 mention 实例因 judge 批处理只判一次而只计 1 个证据；宁可漏确认（保守）不可错确认。跨 chapter 证据自然满足 |
| 4 | single-candidate | bare 一律证据门槛；**qualified + anchor ∉ 候选集 → anchor-mismatch 不可确认（不入 observation，永不 alias）**——覆盖 M5/M16 高风险场景 |
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
| M5 | 单候选错误（翠翠的父亲 anchor 翠翠 ∉ 候选 [顺顺]，judge 误判 顺顺） | **anchor-mismatch 不可确认**：不记 observation、不入图；**永不 alias（无任何晋升路径）** |
| M6 | 同一错误上下文重复两次（同 chunk 两处 翠翠的父亲→顺顺） | 证据按 chunk 去重 = 1 → 不 alias |
| M7 | 限定 + 裸混合（同 chunk：翠翠的父亲 + 父亲，judge 均判 顺顺） | 翠翠的父亲：anchor ∈ 候选 → 安全路径 / anchor ∉ 候选 → 不可确认；父亲（bare）→ observation；互不干扰 |
| M8 | 已确认 alias 回归（爸爸→顺顺 confirmed 后，ch3 再出现） | 直接 alias（不重复累计、不剔除） |
| M9 | 翠翠的祖父（anchor 翠翠 ∈ 候选 [翠翠,祖父]，judge 判 祖父） | **单次 alias 保持**（安全路径，T-b8 回归） |
| M10 | 哥哥→大老（GENERIC） | RC3 路径不变（不触发证据机制） |
| M11（重定义） | **1 evidence + 无 conflict → 全书末保持 observation**（显式验证 gate 不被绕过） | 不确认；mention 不入图 |
| M12（重定义） | **跨 canonical 冲突**：父亲（bare）ch1 判→顺顺、ch2 判→祖父 | blocked；父亲 全部 observation 作废；永不确定；不入图 |
| M13（新增） | 跨 canonical 冲突变体：同一 bare mention 两 canonical 各 1 证据 | blocked（不允许分别累计独立确认） |
| M14 | 老船夫→祖父（descriptive epithet，LLM category=PERSON） | **不触发证据机制**；保持现有单次 alias 路径 |
| M15 | 父亲（LLM category=None → PERSON fallback） | 不触发（D5 一致 Known Limitation）；保持现状 |
| **M16（新增）** | **同一 qualified role（翠翠的父亲）anchor 连续缺席候选、两个不同 chunk 均错误 resolves_to 同一 C（顺顺）** | **必须不确认**：每次判定均为 anchor-mismatch → 不记 observation → 永无 ≥2 证据 → 不入图 |

**回归**：T-a 全量（P16-a）、T-b 全量（P17，deferred/unresolved 行为零变化）、test_hygiene（RC2/RC3）、test_resolver（既有 alias 路径）、integration 15。

## 8. Trade-offs（v3 修订）

- **首次信息损失（无兜底补偿）**：bare role 首次 mention 输出剔除；若全书仅 1 次证据 → 永久不入图（父亲 场景）。这是「错确认防 sink」与「信息完整」的取舍——**本设计明确优先防错**（v2/v3 删除了 v1 的兜底补偿，因为兜底正是 gate 的洞）。
- **父亲 不 alias 顺顺**：跨人物裸 role 不 sink（P16-b 核心目标）；「作父亲的」不入图。
- **qualified anchor 缺席的合法判定会被拒绝（M16 代价面）**：若锚点人物恰不在场但 judge 判对（合法单次），会漏 alias——保守取舍；真实数据中 qualified 合法场景（翠翠的祖父）锚点均在候选集，无实际损失。
- **触发依赖 LLM category（D5 同哲学）**：category=None/PERSON 的裸词不触发（父亲 若被标 PERSON 则保持现状 judge 吸收）——与 P17 D5 一致的已知限制，**不引入 classifier**；若实测覆盖不足，走 P06 follow-up。
- **descriptive epithet 保护**：老船夫 类不进机制（category=PERSON）→ 现有 alias 路径零变化。
- **GENERIC 例外**：哥哥/弟弟 保持单次 alias（RC3 锁），依赖其专属性强；若未来出现跨人物 GENERIC，另议。
- 零额外 LLM 调用；确定性计数成本可忽略。

## 9. 不变量 / Do Not Do

- 不修改 hygiene.py、RC2/RC3、P16-a（section/provisional）、P17（deferred/unresolved）、P017 D5、merge bridge、judge 契约、prompt、Neo4j schema、并发/超时。
- 不把 父亲/爸爸/爹爹/任何 role 词加入 GENERIC 或 hard filter。
- **observation 永不自动晋升**（不存在 finalize/末次兜底路径）。
- 不改 `_resolve_name` 的 PERSON/None 分支；不改 `_register`/`_first_seen`。
- judge 每 chunk 至多一次；证据机制零额外 LLM 成本。
- 已确认 alias 不自动撤销；跨 canonical 冲突 → blocked（只增不改）。

## 10. 后续

- 实现前以 M1-M16 固化当前行为基线（先写测试，全红 → 实现 → 全绿）。
- 实现范围：resolver 新增 `_role_observations/_role_confirmed/_role_blocked` + `classify_role_mention` + anchor 在场判定（锚点 canonical ∈ candidates，确定性）+ evidence 分派；**无 novels.py 变更**。
- 若真实评估显示 LLM category 覆盖不足（父亲 被标 PERSON 未触发）→ 走 P06 follow-up（category 质量），不擅自扩触发范围。
- Group / 关系角色建模：留待未来（P16-b 不引入）。
