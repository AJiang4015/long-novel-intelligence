# PIPELINE_LAYER.md — pipeline 层契约与决策所有权

> 定位：**Layer Contract / Layer Boundary**（本层负责什么、不能负责什么），不是代码使用说明。
> 全局架构地图见 `../../../ARCHITECTURE.md`；本层是项目**最重要的决策层**——所有 ER 行为决策的归属都在这里判定。
> 归因纪律：问题应优先归到**真正拥有该决策的层**，而不是「哪里方便改就改哪里」。

## 1. Responsibility

EPUB 输入 → 抽取 → 消歧 → 合并 → 可写库图数据的全链路内存处理：

```text
epub_reader → sections → chunker → extractor(llm_client) → hygiene
→ resolver → merger
```

## 2. Input contract

| 模块 | 输入 |
|---|---|
| epub_reader | EPUB bytes |
| sections | chapter（标题 + 正文） |
| chunker | chapters + `CHUNK_SIZE` / `CHUNK_OVERLAP` |
| extractor | `Chunk` + `LLMClient` + concurrency（必须来自配置，禁止写死） |
| hygiene | mention name（字符串） |
| resolver | `Chunk` + `ExtractionResult`（整本一个 `EntityResolver` 实例） |
| merger | `list[(Chunk, ExtractionResult)]`（resolved 后，已按 chunk_id 升序） |

## 3. Output contract

| 模块 | 输出 |
|---|---|
| epub_reader | chapters（含标题/正文结构） |
| sections | 每个 chapter 的 `SectionType`（METADATA/EPIGRAPH/BODY/TRAILER，默认 BODY） |
| chunker | `Chunk` 列表 |
| extractor | `ExtractionBundle`（results + failed `FailedBlock`） |
| hygiene | `MentionCategory \| None`（仅 COLLECTIVE/INVALID/GENERIC 精确词，其余 None） |
| resolver | resolved `ExtractionResult` + `canonical_aliases` + hygiene_stats + merge_evidence/merge_map |
| merger | `MergedGraph`（persons + relationships） |

## 4. Decision ownership（决策所有权矩阵）

```text
Extractor（extractor.py + llm_client.py + epub_reader.py + sections.py + chunker.py）
  owns:
    mention discovery（是否被抽取、抽取覆盖）
    extraction category（LLM 标注 category；category=None 是契约允许值，不是错误）
    chunk 切分与 section 分类（确定性启发式）
    并发抽取编排、重试/错误区分（retryable vs validation，validation 不重试）
  does NOT own:
    canonical resolution
    alias admission
    merge decision

Hygiene（hygiene.py）
  owns:
    deterministic normalization / category hygiene：
      COLLECTIVE / INVALID 硬过滤；relational generic 精确词表（RC3，D-7）
  does NOT own:
    返回 GENERIC / DESCRIPTIVE / COMPOSITE 分类（返回 None → 交 LLM category）
    任何语义判定（不解释上下文）

Resolver（resolver.py）
  owns:
    mention → canonical resolution（recall → judge → admission → registration）
    role admission（P16-b evidence gate：bare ≥2 证据 / qualified 对齐 + anchor 在场，D-5）
    alias registration（known / canonical_aliases 整本持续；首现定主名）
    effective category usage（LLM category → hygiene 兜底 → legacy PERSON fallback）
    provisional / promotion / flush（非正文注册门控）
    deferred / unresolved（P17 D2：无法确认 → 不注册）
  does NOT own:
    merge decision / merge apply（decide_merges 产物仅交 merger 与 db 执行）

Merger（merger.py）
  owns:
    cross-chunk aggregation（PersonAgg / RelAgg / weight / confidence / evidence cap）
    merge decision（b1：decide_merges 纯内存决策，不改写 resolver 状态）
    merge application（b2：merge_map → db 单事务执行）
  does NOT own:
    semantic re-interpretation of extraction（不得改写抽取语义）

Lineage（lineage.py）
  owns:
    observation only（事件记录：chunk_start / mention_enter / recall / judge /
      admission / registration / merge_*；lineage_id join；终态一次性 flush JSONL）
  MUST NOT:
    participate in business decisions
    modify resolver / extraction output
    alter merge behavior
    （默认关闭 ER_LINEAGE=0，no-op 零开销；D-8）
```

### 归因链（六类失败 → 层 → 问题）

> 固化：先归到**拥有该决策的层**，不是「哪里方便改就改哪里」。本链是六类失败归因的唯一权威映射（AGENTS/PROCESS/DECISIONS/PROBLEM 均引用此处）。

```text
extraction coverage failure（抽取覆盖缺失）   → extractor 层    → P017 D5-a
≠ recall failure（候选召回）                 → resolver recall → P08
≠ judge failure（判定非确定性/误判）          → resolver judge  → P06
≠ admission failure（准入拦截误判）           → resolver role  → P16-b / P18
≠ registration failure（注册/alias 策略）     → resolver 注册   → P17 D2
≠ merge failure（跨 chunk 合并）              → merger         → merge INCONCLUSIVE
```

## 5. Allowed dependencies

> 记号：`A → B` 表示 A 依赖（import）B。以下为代码事实（2026-08-27 快照）。

- pipeline → `schemas`（契约类型：`MentionCategory` / `ExtractionResult` / `PendingMention` / `AliasJudgeResult` 等）：`llm_client` / `hygiene` / `extractor` / `resolver` / `merger` 均依赖 schemas
- pipeline 内部：
  - `sections`：**无任何 app 内依赖**（循环导入锚点，必须保持独立；否则 epub_reader → sections → epub_reader 成环）
  - `epub_reader` → sections（`classify_chapter`）
  - `chunker` → epub_reader + sections
  - `extractor` → chunker + llm_client + schemas
  - `resolver` → chunker + lineage + sections + hygiene（运行时局部 import）+ schemas
  - `merger` → chunker + schemas
  - `lineage` → config（无 pipeline 内部依赖；不 import resolver / merger，见 §6）
- 依赖注入：judge（`llm_client.judge_aliases` / `judge_merges`）由 api 层注入，resolver 本身不创建 LLM 客户端

## 6. Forbidden dependencies

- pipeline **不得** import `api`（不接触 HTTP）
- pipeline **不得**直接访问 Neo4j（持久化只经 `db` 层）
- pipeline **不得**依赖 `models`（job 状态机是 api 层关注点）
- lineage **不得** import resolver / merger（观测不依赖被测对象）

## 7. Invariants

- `EntityResolver` 一次 ingest 一个实例；`known` / mention index 整本持续
- resolver 对 chunk 的处理按 chunk_id 升序（确定性）
- merger 输入先按 chunk_id 排序（多次运行结果稳定）；self-loop 防御性丢弃；evidence 保留前 `EVIDENCE_CAP` 条
- hygiene 只返回 COLLECTIVE/INVALID/GENERIC 精确词，其余 None（不越权分类）
- lineage 默认关闭时全部方法空返回，判定路径逐字节不变
- 不把 父亲/母亲/祖父 加入 generic 词表（D-7）；不引入 classifier 绕过 D5（D-10）

## 8. Failure ownership

| 失败 | 归属 | 暴露方式 |
|---|---|---|
| LLM 抽取失败（429/5xx/意外） | extractor（重试后仍失败） | `FailedBlock` → job failed_blocks |
| LLM validation 错误 | extractor（不重试） | `FailedBlock`（`LLMValidationError`） |
| judge 判定失败/异常 | resolver | failed 记录 + 后续 chunk 继续（P06 归因） |
| 无法确认的 DESCRIPTIVE/COMPOSITE | resolver（unresolved，D-9） | 输出剔除 + 计数，**不注册** |
| merge judge 一次异常 | merger（batch failed，INCONCLUSIVE） | merge_stats 记录；**不等于算法失败** |

## 9. Testing expectations

- unit（全 mock，无网络/Neo4j）：`tests/unit/test_{resolver, resolver_context, resolver_descriptive, role_policy, hygiene, merge, merger, chunker, sections, llm_client, lineage}.py`
- resolver 语义锁死用例（`test_resolver.py`）**不得削弱断言**（`../../../TESTING.md` §8 回归清单）
- 修改 `resolver.py` 后必跑 `test_resolver*.py` / `test_hygiene.py` / `test_sections.py` 全量回归（以 `../../../TESTING.md` §8 为准）
- 修改 ER 相关代码后跑全量 unit + integration

## 10. Typical changes allowed here

- 抽取 prompt 调整（经 `../../../PROCESS.md` §5 准入：Problem Record + Spec + Review）
- resolver 决策表 / role gate / category 策略调整（同上准入；P16-b 冻结例外，见 D-6）
- hygiene 规则词表调整（需跑全量回归；换语料时按 D-7 评估）
- merger 聚合/合并逻辑调整（b1/b2 边界不可破坏，D-13）
- lineage 事件类型扩展（纯观测，不改变判定）

## 11. Changes that must be implemented elsewhere

- 写库 / 删除 / 事务：→ `db` 层（`../db/DB_LAYER.md`）
- HTTP 契约 / 编排顺序 / job 状态：→ `api` 层（`../api/API_LAYER.md`）
- 契约类型 / 枚举语义：→ `schemas` 层（`../schemas/SCHEMA_LAYER.md`）
- 让 lineage 参与判定、改变冻结组件（P16-b）、新增数据标签/关系类型：先走 `../../../PROCESS.md` 立项与评审
