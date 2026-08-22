# V0.2.4 Mention Hygiene / Collective Mention Filtering — 设计文档

- **日期**: 2026-08-23
- **版本**: V0.2.4（修订版，基于 c4064416 过度合并诊断）
- **状态**: 设计评审中（未实现，不修改任何代码 / Neo4j 数据）
- **前置**: V0.2.3-a（strong 候选）、V0.2.3-b1/b2（canonical merge）已合入

## 1. 背景与问题

《边城》c4064416（V0.2.3 全管线）出现严重过度合并：extraction 把集合/泛指 mention（`两个儿子`）输出为 Person → 注册为 canonical → alias judge 单候选吸收真实人物（天保/傩送/岳云/大儿子）→ `_index` 膨胀 → text co-occurrence 子串扩散 → canonical merge bridge pair 风暴 → 16 个 alias 全部并入 `两个儿子`。

根因链：
```
Extraction → 集合/泛指 mention 注册为 Person canonical
→ Alias Judge 单候选吸收真实人物
→ _index 膨胀
→ text co-occurrence 扩散
→ canonical merge bridge pair 风暴
→ 严重 false merge
```

V0.2.4 解决最上游：**Mention Hygiene / Collective Mention Filtering**。

## 2. 目标与不变量

**目标**：COLLECTIVE/INVALID mention 永不成为 Person canonical；GENERIC 永不成为 canonical 但可作 alias mention 消歧；DESCRIPTIVE/COMPOSITE 不误伤（正常消歧）。

**必须保持的行为**（对照 V0.2.2 实证）：
- `天保大人` → 可正常 alias resolution（→大儿子/天保）
- `天保大老` → 可正常 alias resolution（→大老）
- `岳云二老` → 可正常 alias resolution（→傩送）
- `翠翠的祖父` → 可正常 alias resolution（→祖父）
- `弟弟`/`年青人`/`妇人` 等 GENERIC → 不成为 canonical，但允许 alias judge 吸收

**明确不做（YAGNI）**：
- 不修改 V0.2.3-b canonical merge bridge 规则（先验证 hygiene 效果；bridge 限制为后续独立任务）
- 不引入 Group / Collective Entity 数据模型
- 不修改 Neo4j schema / API / GraphResponse / 前端
- 不引入额外 LLM hygiene 调用（category 作为 extraction 契约的一部分）

## 3. Mention 分类（MentionCategory Enum）

```python
class MentionCategory(str, Enum):
    PERSON = "person"           # 专名（天保/傩送/翠翠/祖父/顺顺）
    GENERIC = "generic"         # 泛指称谓（年青人/妇人/哥哥/弟弟/死去的人）
    COLLECTIVE = "collective"   # 集合称谓（两个儿子/兄弟二人/父子三人/两弟兄）
    DESCRIPTIVE = "descriptive" # 描述性称谓（翠翠的祖父/顺顺大儿子）
    COMPOSITE = "composite"     # 复合称谓（岳云二老/天保大老/天保大人/傩送二老）
    INVALID = "invalid"         # 畸形（空/纯数字/符号/超长）
```

**使用 Pydantic Literal/Enum，不使用任意 string**（`Character.category: MentionCategory | None`，LLM 未输出时 None）。

## 4. 分类来源与优先级

| 层 | 负责 | 说明 |
|---|---|---|
| **deterministic hard rules**（hygiene.py 纯函数） | 明确 COLLECTIVE / INVALID | 量词模式（`[一两二三四五六七八九十]个?[儿子兄弟儿女]`、`兄弟二人`、`父子三人`、`两弟兄`）；空/纯数字/超长/符号 |
| **LLM category**（extract 契约输出） | PERSON / GENERIC / DESCRIPTIVE / COMPOSITE | extract 对每个 character 输出 category；`None` 时走规则兜底 |

**优先级**：deterministic hard rules 判定为 COLLECTIVE/INVALID 时**以规则为准**（覆盖 LLM category，防止 LLM 误标）；其余以 LLM category 为准；`None` 且规则未命中 → 按 PERSON 处理（保守，不误伤）。

## 5. Resolver 决策表

| category | 有候选 | 无候选 |
|---|---|---|
| PERSON | 正常 alias judge | 注册 canonical |
| GENERIC | 进入 alias judge（judge 明确通过 → alias；null → 丢弃） | **丢弃，不注册 canonical** |
| COLLECTIVE | 硬过滤（无论候选） | 硬过滤 |
| DESCRIPTIVE | 进入 alias judge | **允许注册 canonical**（不静默丢人物） |
| COMPOSITE | 进入 alias judge | **允许注册 canonical**（不静默丢人物） |
| INVALID | 硬过滤 | 硬过滤 |

**被过滤 mention 不得进入**：`known` / `_index` / `canonical_aliases` / `merge_evidence` / canonical merge。

**关键防护**：
- GENERIC 无候选 → 丢弃（不注册）；GENERIC 有候选但不因「唯一候选」自动成为 alias——必须 judge 明确判定（现有 `_apply_judge` 已要求 resolves_to 来自候选，天然满足；需确认 GENERIC 不绕过 judge）
- COLLECTIVE/INVALID 在 resolver 处理前由规则拦截，不进 chunk_names / confirmed / text_confirmed 匹配源

## 6. 数据流

```
extract(LLM, 输出 characters + category)  [category 缺失 → None]
  ↓
deterministic hygiene rules（hygiene.py classify_mention）
  ├─ COLLECTIVE / INVALID → 硬过滤（不进 chunk_names；relation endpoint 涉及则丢该关系）
  └─ 其余 → 携带 category 进入 resolver
      ↓
resolver._resolve_name（按 §5 决策表）：
  - GENERIC 有候选 → pending → alias judge
  - GENERIC 无候选 → 丢弃
  - DESCRIPTIVE/COMPOSITE 有候选 → pending → alias judge
  - DESCRIPTIVE/COMPOSITE 无候选 → 注册 canonical（暂允许）
  - PERSON → 正常
  - COLLECTIVE/INVALID → 永不进入
  ↓
merge_extractions → apply_aliases → apply_merges → upsert_graph（V0.2.3-b 不变）
```

## 7. Relation endpoint 处理

| category | 作为 endpoint |
|---|---|
| COLLECTIVE / INVALID | **丢弃该关系**（不创建伪 Person / Group） |
| GENERIC | 有候选 → 正常消歧；无候选（mention 丢弃）→ 丢弃该关系 |
| DESCRIPTIVE / COMPOSITE | 正常，按 alias/canonical 规则 |
| PERSON | 正常 |

## 8. 统计（job stats）

```json
"mention_hygiene": {
  "collective_filtered": 0,
  "generic_filtered": 0,
  "descriptive_resolved": 0,
  "composite_resolved": 0,
  "invalid_filtered": 0
}
```

- `generic_filtered` 只统计**最终被丢弃**的 GENERIC，不统计成功解析为 alias 的
- `descriptive_resolved` / `composite_resolved` 统计成功消歧（成为 alias 或 canonical）的数量
- 统计进 job stats，不污染 failed_blocks

## 9. 最小代码改动范围

| 模块 | 改动 |
|---|---|
| `schemas/llm.py` | 新增 `MentionCategory` Enum；`Character.category: MentionCategory | None = None`（向后兼容） |
| `llm_client.py` | EXTRACTION_SYSTEM_PROMPT 要求输出 category；容忍缺省 |
| `pipeline/hygiene.py`（新建） | `classify_mention(name) -> MentionCategory | None`（deterministic hard rules：COLLECTIVE/INVALID 模式）；`is_hard_filtered(name) -> bool` |
| `resolver.py` | ① resolve() 开头对 chunk_names 过滤（COLLECTIVE/INVALID 不进 confirmed/text_confirmed）② `_resolve_name` 按 category 决策（GENERIC 无候选丢弃；DESCRIPTIVE/COMPOSITE 无候选注册）③ `_apply_judge` 确认被过滤名不写 known ④ merge_evidence 收集前排除被过滤名 |
| `merger.py` | 无需改（resolved 输出已不含被过滤名） |
| `novels.py` | job stats 增加 mention_hygiene |
| `tests/unit/test_hygiene.py`（新建） | 测试矩阵见 §10 |

## 10. 测试矩阵

### 10.1 COLLECTIVE 硬过滤
1. `两个儿子` / `兄弟二人` / `父子三人`：不注册 canonical；不在 known/_index/canonical_aliases；无 merge_evidence
2. `两个儿子` 作为 relation endpoint：该关系被丢弃

### 10.2 INVALID 硬过滤
3. 空 / 纯数字 / 超长 mention：不注册、不进入任何状态

### 10.3 GENERIC
4. `年青人`/`妇人`/`哥哥`/`弟弟` 有候选 → 必须经过 alias judge；judge 明确通过 → alias；judge null → 丢弃
5. `哥哥`/`弟弟` 不因「唯一候选」自动成为 alias（必须 judge 判定）
6. `年青人` 无候选 → 丢弃，不注册 canonical

### 10.4 DESCRIPTIVE / COMPOSITE 不误伤
7. `天保大人` → 正常 alias resolution（→大儿子/天保）
8. `天保大老` → 正常 alias resolution（→大老）
9. `岳云二老` → 正常 alias resolution（→傩送）
10. `翠翠的祖父` → 正常 alias resolution（→祖父）
11. DESCRIPTIVE/COMPOSITE 无候选 → 允许注册 canonical（不静默丢失）

### 10.5 正常 PERSON 不误伤
12. `天保`/`傩送`/`翠翠`/`祖父`/`顺顺` 不被 hygiene 误过滤，注册/消歧行为不变

### 10.6 状态污染
13. 被过滤 mention 不得进入 known/_index/canonical_aliases/merge_evidence

### 10.7 回归
14. test_resolver（23）+ test_merge（11）+ test_merger（21）+ integration（15）全部保持 PASS

## 11. 对 P08/P09 的影响

- **P08**：hygiene 消除集合 canonical 虹吸，P08 的「真实人物分裂」诊断不再被污染掩盖；记录补充「集合 canonical 虹吸」子案例
- **P09**：V0.2.4 是 P09 的正式落地——分类方案、过滤位置、COMPOSITE/DESCRIPTIVE 不误伤原则、成本控制（category 并入 extract 契约）写入记录

## 12. 潜在风险

1. **过滤过度误伤**：规则把 `翠翠的祖父`/`岳云二老` 误判 → 测试 7-11 锁死；DESCRIPTIVE/COMPOSITE 无候选允许注册兜底
2. **GENERIC 丢弃丢关系**：`哥哥→弟弟` 等关系因 endpoint 丢弃而丢——可接受（数据完整性优先）
3. **LLM category 不稳定**（P06 域）：extract 对 category 的判定非确定 → 规则兜底 + 测试固定断言；category 是辅助信号，resolver 决策以规则 COLLECTIVE/INVALID 为准
4. **旧数据不修复**：c4064416 的 `两个儿子` 节点不迁移（范围外）

## 13. 已确认评审决策（2026-08-23）

1. GENERIC 定义：不注册 canonical；可作 alias mention 消歧；不进 established canonical/merge pair
2. COLLECTIVE 才硬过滤（两个儿子/兄弟二人/父子三人/两弟兄）
3. INVALID 硬过滤
4. DESCRIPTIVE/COMPOSITE 不简单全量过滤：有候选 → alias judge；无候选 → 允许注册 canonical
5. category 优先级：hard rules 只负责 COLLECTIVE/INVALID；LLM category 负责 PERSON/GENERIC/DESCRIPTIVE/COMPOSITE；resolver 按 category 决策
6. `Character.category` 用 Pydantic Enum（MentionCategory），不用任意 string
7. V0.2.4 不修改 canonical merge bridge 规则（先验证 hygiene 效果；bridge 限制为后续独立任务）
8. 保持现有行为：天保大人/天保大老/岳云二老/翠翠的祖父 正常 alias resolution；弟弟/年青人/妇人 不建 canonical 但允许 alias judge
9. `两个儿子`：不创建 Person；V0.2.4 不创建 Group；丢弃其 relation endpoint（不建伪 Person）
