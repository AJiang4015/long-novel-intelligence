# V0.2.5-a：Context-aware ER（非正文 section 注册门控 + provisional canonical）— 设计文档

- **日期**: 2026-08-26
- **版本**: V0.2.5-a（P16 专项）
- **状态**: 设计评审通过（决策锁定 2026-08-26），**未实现**
- **前置**: V0.2.4 冻结（RC2 `0febdc1`、RC3 `83db5f7`/`9f3b85f`）；真实评估 job `634f7f96` / novel `5c311fb3`

## 1. 背景与问题（P16）

真实《边城》评估（job `634f7f96`）出现 **Metadata / Epigraph 对 canonical 首现的污染**：

- `父亲` canonical（mc=13，chapters=[2,5,6,8,11,12,13,14,16,19,20,22,23]）吸收 顺顺/顺顺大哥/顺顺船总/船总顺顺/翠翠的父亲/中年人/爹爹；`MATCH Person name="顺顺"` 无记录。
- 补充证据（只读复核）：`沈从文`（mc=3，ch=[1,2,3]，alias 从文）与 `兆和`（mc=1，ch=[3]）为**纯非正文 Person 节点**；题记「我的祖父，父亲，以及兄弟，全列身军籍」被直接建成 `沈从文-[family]->祖父/父亲/母亲`（0.95）与 `沈从文-[love]->兆和` 边；`祖父`（ch 含 2）、`母亲`（ch 含 3）为**隐形污染**（字符串与正文一致，但 first_seen/mc/chapters 被非正文污染）。

## 2. 关键证据

| # | 证据 | 结论 |
|---|---|---|
| 1 | EPUB 结构（25 章，全部无 item title）：ch1 版权(14) / ch2 题记(1670) / ch3 新题记(404) / ch4–24 正文 / ch25 推广(105) | 非正文章节**内容可识别**；无标题可用 → 分类必须内容/位置启发式 |
| 2 | ch2 题记「我的祖父，父亲，以及兄弟，全列身军籍…」含 父亲×1、祖父×1 | `父亲` 首现于题记（作者自述语境），非故事人物 |
| 3 | Neo4j 章节集含 1/2/3/25 的 canonical 共 5 个：沈从文/父亲/祖父/母亲/兆和 | 非正文污染范围精确可列 |
| 4 | `沈从文-[love]->兆和`、`沈从文-[family]->祖父/父亲/母亲`（0.95） | 题记派生边直接入图 |
| 5 | ch5b（ch5 切块 B=[3600,4609)）：顺顺@3820 与「作父亲的…」@~4430 同 chunk | `顺顺 → 父亲` 的 judge 吸收在**正文 chunk 内**完成，sink 形成 |
| 6 | `父亲` chapters 中 6/8/11/12/13/14/19/20/22/23 均无「父亲」原文 | 全部来自 alias（顺顺等）扩散 → canonical sink 实证 |
| 7 | `父亲` chapters 无 4（正文 4 处）——ch4 chunk 为 8 个 ReadTimeout 失败块之一 | 单次运行吸收路径含 LLM 失败噪声（P06/RC1 域） |

## 3. Problem Boundary

1. **P16 = 非正文（版权/题记/新题记/推广）对 canonical 首现的污染**；不是词表问题。`祖父/父亲/母亲` 是正文真实人物（祖父=老船夫 核心人物），**全局 GENERIC 化禁止**（RC3 已锁；P009 Do Not Reopen）。
2. **P16 ≠ P16-b（正文内 relational-role canonical sink）**：即使修掉题记首现，正文内部「父亲」仍歧义（翠翠的父 / 顺顺 / 作渡船夫的父亲 ≥3 人），ch4/ch5 正文共现下 `顺顺→父亲` 吸收仍可能发生。**P16-b 单独诊断，V0.2.5-a 不承诺解决**（勿因未解决而判 -a 失败）。
3. **P16 ≠ P17**：上下文注册门控（P16）vs DESCRIPTIVE 延迟注册（P17）——共用同一个 canonical 注册决策缝，但信号（section_type vs category+chunk 内证据）与策略各自独立。

## 4. 锁定决策（评审 2026-08-26）

- **D1**：非正文专名（兆和/沈从文）**无正文确认 → 不入图**；保留于抽取输出与 ER 处理（不被 hygiene 误删），flush 时排除出图并计数；以其为端点的关系随端点丢弃。
- **D2**：section 分类 = 确定性内容/位置启发式；**禁止「跳过前 N 章」**；默认 BODY（保守，只有高置信分类触发限制）。
- **D3**：provisional 晋升条件 = BODY 同名字出现（known-hit）或 judge 并入 BODY canonical；晋升后 mc/chapters 只计 BODY chunk（非正文 chunk 不参与统计）。
- **D4**：非正文 DESCRIPTIVE/COMPOSITE **永不注册**（有候选参与既有单次 batch judge；无候选丢弃并计数）。
- **D5**：非正文 PERSON 注册**恒为 provisional**（无候选分支 / judge null / judge 异常 三路统一）。
- **D6**：provisional **不得进入任何候选源**（`confirmed` / `text_confirmed` / `_recall`），直到晋升（→ 测试 T-a14 锁死）。

## 5. 设计

### 5.1 SectionType + sections.py（新模块）

```python
class SectionType(str, Enum):
    METADATA = "metadata"     # 版权/封面/目录
    EPIGRAPH = "epigraph"     # 题记/新题记/序/前言（PREFACE 并入）
    BODY = "body"             # 正文
    TRAILER = "trailer"       # 推广/广告/后记标记

def classify_chapter(chapter: Chapter, index: int, total: int) -> SectionType:
    # 优先级：标题关键词 → 首非空行标记 → 正文序号 → 位置弱信号 → 默认 BODY
```

- 标题关键词（若 EPUB item 有 title）：题记/新题记/序/自序/前言/引言/版权/目录/跋/后记/致谢/广告。
- 首非空行标记（《边城》验证，标注为项目级非通用）：`版权信息`、`作者：`、`题记`、`新题记`、`关注公众号`、`微信搜索`、`mp.weixin`。
- 正文序号：`一/二/三…`、`1./1、`、`第N章`（含中文数字）→ BODY。
- 位置弱信号（仅兜底，低置信）：首章极短+版权特征 → METADATA；末章+广告标记 → TRAILER。
- 未命中 → **BODY**（保守默认）。

### 5.2 管线

- `epub_reader.py`：`Chapter.section_type`，`read_epub` 内调 `classify_chapter`。
- `chunker.py`：`Chunk.section_type` 继承自 chapter；overlap 不跨章（已核实）→ **chunk 永不混 section**。

### 5.3 resolver 注册门控（`_resolve_name` 无候选分支 + `_register`）

| section | GENERIC | COLLECTIVE/INVALID | DESCRIPTIVE/COMPOSITE | PERSON / category=None |
|---|---|---|---|---|
| BODY | 丢弃（RC3） | 硬过滤（RC2） | 有候选→judge；无候选→**deferred（V0.2.5-b）** | 无候选→注册 canonical（不变） |
| 非正文 | 丢弃（RC3） | 硬过滤（RC2） | 有候选→judge（并入单次 batch）；无候选→**丢弃计数** | 注册为 **provisional**（三路统一） |

provisional 状态：

- `_provisional: set[str]`（或独立 buffer，实现二选一；推荐独立集合 + known-hit 前置检查）。
- 注册时**不写入 `_index`** → `_text_mentions`/`_recall` 天然不可见；`known[name]=name` 保留以支持 known-hit 晋升路径。
- 晋升：BODY chunk 中该名字出现在抽取输出 → known-hit 分支先查 `_provisional` → 移出集合（晋升为正式），此后正常进入候选源。
- **Flush**（`finalize()`，novels.py 在 `upsert_graph` 前调用）：未晋升 provisional → 移出 known/aliases；以其为端点的关系丢弃（沿用 RC2 endpoint 丢弃模式）；计数。
- 非正文 chunk 的解析结果**不参与** `_canonical_chunks`/`_canonical_chapters` 统计（mc/chapters 天然只含 BODY 证据）。

### 5.4 stats

`mention_hygiene` 扩展：`nonbody_person_provisional`（非正文 PERSON 注册数）、`nonbody_descriptive_dropped`、`nonbody_provisional_dropped`（flush 未确认数）。

## 6. 测试矩阵（全 deterministic，mock extract/judge，epub_factory 夹具）

| ID | 用例 | 期望 |
|---|---|---|
| T-a1 | EPIGRAPH 父亲（DESCRIPTIVE，无候选） | 不注册 canonical，不进 known |
| T-a2 | BODY 父亲 无候选 | 照旧可注册 canonical |
| T-a3 | EPIGRAPH 兄弟（GENERIC） | 丢弃（RC3 语义在 epigraph 成立） |
| T-a4 | BODY 兄弟 有候选 | 可 alias、永不 canonical（RC3 回归） |
| T-a5 | EPIGRAPH 兆和（PERSON） | 保留在 chunk 输出；provisional；**排除出候选源** |
| T-a6 | 兆和 flush 未确认 | 出图时排除 + 计数；端点关系丢弃 |
| T-a7 | 祖父 epigraph provisional → BODY 同名字 | 晋升为正式；mc/chapters 只计 BODY chunk |
| T-a8 | section_type=BODY 不影响正常 canonical（傩送 无候选→canonical） | 不变 |
| T-a9 | 非正文关系端点未确认 | 关系丢弃（RC2 端点规则） |
| T-a10 | RC2 回归（全 section） | COLLECTIVE/INVALID 硬过滤不变 |
| T-a11 | 分类：版权→METADATA/题记→EPIGRAPH/新题记→EPIGRAPH/一→BODY/推广→TRAILER | 精确 |
| T-a12 | 未知首行 / 无标记 | 默认 BODY（保守） |
| T-a13 | chunk 不混 section | chunk.section_type == 所属 chapter |
| **T-a14** | **provisional 不得进入 BODY recall candidate source**（ch1 EPIGRAPH 注册 兆和 provisional → ch2 BODY 原文含「兆和」子串+提取 M → 断言 M 的 candidates 与 text_confirmed 均不含 兆和；ch3 BODY 提取 兆和 → 晋升 → ch4 起候选源才含 兆和） | provisional 晋升前对候选层完全不可见 |

## 7. 不变量 / Do Not Do

- RC2/RC3 全部语义不变（GENERIC 永不 canonical；硬过滤三处排除；输出剔除）。
- PERSON 无候选立即注册（`test_new_name_no_candidate_is_new_canonical_no_llm` 锁死）不变。
- 不动 merge bridge、judge 契约、extract prompt、Neo4j schema、并发/超时。
- 不把 父亲/母亲/祖父 加入 generic 词表；不做「跳过前 N 章」；不整体忽略非正文 character（兆和 必须在抽取输出中）。
- 不引入 LLM 分类器判定 section（确定性规则优先）。

## 8. 后续

1. 实现后全量回归（hygiene 59 / resolver+merger+llm_client 124 / unit 148 / integration 15）。
2. 下一次真实《边城》评估验收指标（不只比 Person 数量）：
   - **非正文 canonical 数量**（期望：沈从文/兆和 等纯非正文节点消失）；
   - **provisional → promoted / provisional → dropped** 计数（期望：兆和/沈从文 dropped；祖父/母亲 类 promoted）；
   - **父亲 first_seen 不再含题记（ch2）**；
   - ⚠️ **若 `顺顺→父亲` 仍发生：不判 P16-a 失败**——那是已切出的 **P16-b（正文 relational-role canonical sink）**，本次评估反而是 P16-b 第一次干净观察（不再与题记污染混杂）。
3. **P16-b**（正文 relational-role canonical sink，父亲/顺顺 类）另行诊断设计，不并入 -a。
