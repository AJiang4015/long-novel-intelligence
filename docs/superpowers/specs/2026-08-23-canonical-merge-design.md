# V0.2.3-b Canonical↔Canonical Merge — 设计文档（修订版）

- **日期**: 2026-08-23
- **版本**: V0.2.3-b（修订版，基于诊断评审意见）
- **状态**: 设计评审中（未实现，不修改任何代码 / Neo4j 数据）
- **前置**: V0.2.3-a（strong 候选永不挤掉，`ed4c388`）已合入

## 1. 背景与目标

已经形成多个 canonical Person 后，后续桥接 mention 才证明它们属于同一人物。例：

```
Person A: canonical=大儿子, aliases=[天保, 天保大人]
Person B: canonical=大老,   aliases=[天保大老, 儿子]
桥接 mention: 天保大老
目标: canonical=大儿子, aliases=[天保, 天保大人, 大老, 天保大老, 儿子]
```

**必须遵守**：「首次出现定 canonical，后续不重新选择 canonical」。

**禁止**：embedding / vector DB / 全局聚类 / 全局 canonical 两两比较 / 自动传递闭包合并 / canonical 重命名 / 旧数据迁移 / 前端 / GraphResponse / API 修改。

## 2. 总体架构：拆为两个阶段

| 阶段 | 目标 | 交付 | 落库 |
|---|---|---|---|
| **V0.2.3-b1** | Canonical Merge Decision（**纯 decision，不改 resolver 状态**） | bridge evidence → canonical pair → merge judge → `merge_map` | **不写 Neo4j** |
| **V0.2.3-b2** | Apply Canonical Merge（**唯一应用 merge_map 处**） | `merge_map` → MergedGraph 合并 → 单事务写库 | 写 Neo4j |

b1 先行、稳定后再做 b2。b1 产出 `merge_map` 为 b2 唯一输入契约。

---

## 3. V0.2.3-b1：Canonical Merge Decision

**b1 是纯 decision 阶段（强制）**：只读取 resolver 状态并生成 `merge_map`；**不得修改** `resolver.known` / `resolver._index` / `resolver.canonical_aliases`，也不改写任何 chunk 的 resolved 输出。所有状态变更（PersonAgg / relationships / Neo4j）一律推迟到 b2。b1 输出的 `merge_map` 是 b2 的唯一输入契约。

### 3.1 输入 / 输出

```
输入: chunks + ExtractionResult（抽取后）+ EntityResolver 状态
流程: resolve chunks → 收集 bridge evidence → canonical pair 去重 → batch merge judge → merge_map
输出:
{
  "merge_map": { "大老": "大儿子" },          # C_drop -> C_keep
  "stats": {
    "entity_resolution": {
      "merge_candidate_pairs": 12,
      "merged_pairs": 5,
      "rejected_pairs": 6,
      "failed_pairs": 1
    }
  },
  "merge_failures": [{"a": "...", "b": "...", "error": "http_429"}]   # 可选，不污染 failed_blocks
}
```

### 3.2 触发规则（不变）

只允许：**一个 mention 的 candidate canonical 中 ≥ 2 个 established canonical**，才生成 canonical pair。

- candidate 来源可以是 extraction confirmed / text confirmed / weak recall（V0.2.3-a 保证候选完整）
- **只有 established canonical 参与**：established = 在本 chunk resolve 前已在 `known` 且 `known[c] == c`
- 例：mention `天保大老` candidates `[大老, ..., 大儿子]` → pair `(大老, 大儿子)`
- 实现：`resolve()` 开头快照 `established = {c for c in known if known[c] == c}`；pending 阶段对每个 mention 统计 `candidates ∩ established`，≥2 则旁路记录一条 **merge_evidence** 到 `merge_evidence` 列表。**纯旁路，不改变 judge 行为**。

**merge_evidence 记录结构**（每条保存完整上下文，供 pair 去重、judge 输入与调试）：

```json
{
  "mention": "天保大老",                      # 桥接 mention 本身
  "candidates": ["大老", "大儿子", "..."],     # 该 mention 的完整候选（established canonical 部分）
  "pair": ["大老", "大儿子"],                   # 生成 canonical pair（无序，用于 frozenset 去重）
  "chunk_id": 11,
  "chapter_id": 3,
  "text": "前几天顺顺家天保大老过溪时，同祖父谈话…"
}
```

- 一个 mention 若同时命中 ≥3 个 established canonical（如候选含 C1/C2/C3），可生成多个 pair（(C1,C2)、(C1,C3)、(C2,C3)），每 pair 各记一条 evidence（共享同一 chunk_id/chapter_id/text）

### 3.3 pair 去重

- `frozenset(c1, c2)` 去重，同 pair 只判一次
- 候选生成 O(mentions × k²)，k = 每 mention 候选数常数（5-8），**无全局 O(N²) 比较**

### 3.4 merge judge 契约（独立，不复用 judge_aliases）

**输入**（每 pair 两侧信息 + bridge evidence）：

```json
{
  "pairs": [
    {
      "a": {
        "canonical": "大儿子",
        "aliases": ["天保", "天保大人"],
        "first_seen_chunk": 6,
        "mention_count": 12,
        "chapters": [3, 5, 6]
      },
      "b": {
        "canonical": "大老",
        "aliases": ["天保大老", "儿子"],
        "first_seen_chunk": 9,
        "mention_count": 9,
        "chapters": [8, 9, 10]
      },
      "bridge_evidence": [
        {"chunk_id": 11, "chapter_id": 3, "mention": "天保大老", "text": "..."}
      ]
    }
  ]
}
```

**输出**：

```json
{
  "merges": [
    {"a": "大儿子", "b": "大老", "merge": true, "confidence": 0.92}
  ]
}
```

**强制约束**：
- `a`/`b` 必须来自输入 pairs；`a != b`
- `merge` 必须是 bool；`confidence` ∈ [0, 1]
- 禁止生成新 canonical（LLM 不得创造输入之外的任何名字）
- **judge failure → 不 merge**（保持分裂，安全默认）

**数据来源**：resolver 需新增轻量状态（first_seen_chunk 定义见 §3.5；mention_count / chapters 同源统计），以在 b1 阶段提供 judge 输入。

### 3.5 first_seen 定义与 Canonical 选择（C_keep 规则）

**first_seen_chunk 定义（明确）**：**首次确立 canonical 的 chunk_id**——即该名字经 `_register()`（或经 judge 并入前）成为 canonical 的那一刻所在的 chunk_id，**不是原文中该词首次出现的位置**。例：`大儿子` 在 chunk 6 被提取并成为 canonical → `first_seen_chunk("大儿子") = 6`，即使「大儿子」字样在更早 chunk 已出现。

严格：**C_keep = 两个 canonical 中 first_seen_chunk 更小（更早）者**。

- first_seen_chunk 相同 → 确定性 tie-break（如 canonical 字符串升序；实现时固定，写测试锁死）
- **绝不**：改 canonical 名称 / 选最长名字 / 选出现最多名字 / 让 LLM 决定 canonical

### 3.6 merge_map 语义与生命周期

```
merge_map: dict[str, str]     # C_drop -> C_keep（直接映射，非 union-find）
```

- **第一版不引入 union-find**；不因 A≈B、B≈C 自动推导 A≈C——除非 A/C 有独立 merge evidence 且 judge 明确通过
- 提供 `resolve_merge_root(name)`：沿 merge_map 链解析到最终 keep，处理已发生过的 merge
  - 例：`A -> B`、`B -> C`（B 是 C 的 drop 且又有 B→C evidence 时）→ `resolve_merge_root(A) == C`
  - **注意**：只有存在独立 merge evidence 且 judge 明确通过才形成新映射；**绝不**仅凭传递关系自动创建
- 生命周期：b1 构建 → b2 应用 → ingest 结束后随 resolver 实例丢弃（不持久化到 Neo4j；canonical 结果已落库）

### 3.7 错误处理与统计（b1）

- **不写入 `failed_blocks`**：failed_blocks 语义是「chunk pipeline 处理失败」；canonical merge 是整本 resolve 后的 entity merge phase，不属于某个 chunk 的失败
- 统计进 `stats.entity_resolution`（见 §3.1 输出）；失败详情可选进 `merge_failures`
- **confidence threshold 为可配置项**（如 `settings.merge_confidence_threshold`，经 `EntityResolver` 构造参数注入），不硬编码为 0.5；judge failure / confidence 低于阈值 → 不 merge，计入 rejected_pairs

### 3.8 b1 测试（mock merge judge，不调真实 LLM）

1. A/B 同人 → merge_map 产生 A/B merge
2. A/B 不同人 → 不 merge
3. bridge mention 双侧命中 → 产生 pair
4. pair 去重（同 pair 只出现一次）
5. merge judge failure → 不 merge
6. confidence 太低（低于可配置阈值）→ 不 merge
7. first_seen_chunk 更早者成为 keep
8. A/B 已通过已有 merge_map 合并 → 不重复生成 pair
9. 不做全局 O(N²) canonical comparison（构造 >100 canonical 仍线性）
10. **纯 decision 锁死**：b1 执行前后 `resolver.known` / `_index` / `canonical_aliases` 完全不变（快照对比）
11. **merge_evidence 完整**：单条含 mention / candidates / pair / chunk_id / chapter_id / text；mention 命中 3 canonical 时生成 3 条 pair evidence

---

## 4. V0.2.3-b2：Apply Canonical Merge

### 4.1 输入 / 输出

```
输入: merge_map + MergedGraph（merge_extractions 产物）+ resolver.canonical_aliases
流程: PersonAgg 合并 → aliases 合并 → RELATES_TO 重定向/聚合 → self-loop 删除 → Neo4j 单事务写入
输出: 落库后的 Novel 图谱（C_keep 保留、C_drop 删除、关系重定向）
```

### 4.2 PersonAgg 必须真正具备 distinct chunk 语义

**必要改动（merger.py）**：PersonAgg 增加 `chunk_ids: set[int]`，并保证：

```
mention_count = len(chunk_ids)          # 不再用 int 累加
merged_chunk_ids = A.chunk_ids ∪ B.chunk_ids
mention_count = len(merged_chunk_ids)   # 禁止 A.mention_count + B.mention_count
```

**已确认实现（2026-08-23 评审）**：
- `merge_extractions` 聚合阶段同步收集 `chunk_ids`（每个 resolved extraction 将 chunk_id 加入对应 canonical 的 chunk_ids，同 chunk 内重复只保留一次）
- `mention_count` 语义保持 = len(chunk_ids)
- `apply_merges(graph: MergedGraph, merge_map: dict[str, str])`：只读 graph 内已完成 canonical 化的 PersonAgg.aliases，不接收 resolver.canonical_aliases；merge_map 是唯一额外输入；不在 apply_merges 内重建 aliases
- 调用顺序固定：`resolve → merge_extractions → apply_aliases → apply_merges → db.upsert_graph`

**新增测试锁死**：A/B 同 chunk 出现时，合并后 mention_count 只增加 1。

### 4.3 aliases 合并（顺序规则）

合并后 aliases 顺序 = **C_keep 原 aliases → C_drop aliases → C_drop canonical name**：

1. C_keep 原 aliases（保序）
2. C_drop aliases（按 C_drop 的 canonical_aliases 原序）
3. C_drop canonical name（追加末尾）

规则：canonical 本身不进入 aliases；去重（跳过与 C_keep 相同、与已有 alias 重复）；保持首次确认顺序。

### 4.4 RELATES_TO 合并语义

1. **重定向**：所有 `source == C_drop` 或 `target == C_drop` 的边改写为 C_keep
2. **同键聚合**：重定向后相同 `(source, target, type)` 的边合并：
   - `chunk_ids` 做并集
   - `confidence` 按当前语义重新聚合（各确认 chunk confidence 的算术平均，块内重复取首次值）
   - `evidence` 保持 EVIDENCE_CAP（前 5 条，首次发现顺序）
3. **self-loop 删除**：C_keep ↔ C_drop 合并后形成的 self-loop 关系删除（与 extraction self-loop 丢弃语义一致）

### 4.5 Neo4j 写入与事务边界

**现状核实（重要）**：现有 `upsert_graph()`（neo4j.py L39-61）用 `with self._driver.session() as session:` 内循环多次 `session.run()`——Neo4j Python driver 中每次 `session.run()` 是 **autocommit 独立事务**，**不具备**「多语句共享一个事务」的原子性。**设计不得假设其天然原子。**

**最小改动方案**：将写入改为单个显式事务（任选其一，实现时定）：
- 方案 A（推荐）：`session.execute_write(unit_of_work)`——把 C_keep upsert、边 upsert、C_drop 删除包进同一个 unit_of_work 函数，内部共享一个 tx
- 方案 B：`with session.begin_transaction() as tx:` 显式 begin/commit/rollback

**已确认实现选择（2026-08-23 评审）**：采用 **方案 A `session.execute_write(unit_of_work)`**，不用 begin_transaction。`upsert_graph(novel_id, merged, merge_map)` 签名扩展，unit_of_work(tx) 内依次：C_keep Person upsert/update → 全部重定向后 RELATES_TO upsert → C_drop Person DETACH DELETE；三步共享同一 tx，任一步抛异常整体 rollback，不产生半合并状态；不创建新 canonical Person；只删 C_drop；C_keep 的 Person.id 不得变化。

**事务内顺序（保证 id 保留与引用完整）**：
1. C_keep Person upsert（更新 aliases / chunk_ids / mention_count / chapters；`MERGE (novel_id, name)` 已存在 → **id 不变**）
2. 全部合并后 RELATES_TO upsert（端点用 C_keep name）
3. `MATCH (p:Person {novel_id, name: C_drop}) DETACH DELETE p`（顺带删除 C_drop 的旧边）

**幂等**：事务内全部成功才 commit；任一步失败 → 整个事务回滚（不产生半合并状态）。

### 4.6 id 保留策略

- Person.id 由 `MERGE (p:Person {novel_id, name}) ON CREATE SET p.id = uuid4()` 生成；已存在时 SET 不覆盖 id → **C_keep 的 id 天然保持**
- 铁律：**只删 C_drop，绝不删除/重建 C_keep，绝不新建 Person**
- `(novel_id, name)` 唯一约束下 C_drop 与 C_keep name 不同（否则早是同一节点），删除无冲突

### 4.7 rollback / failure behavior

- **单事务失败** → 整体回滚，数据库保持合并前状态；job 走现有异常路径（`status=failed, error=str(exc)`）
- **merge judge 已在 b1 完成**，b2 无 LLM 依赖 → 无 LLM 失败分支
- 合并不改变 job 终态判定（P11 范围外）；merge 统计已入 `stats.entity_resolution`

### 4.8 b2 测试（mock merge judge，不调真实 LLM）

**单元**：
1. Person aliases 合并（顺序：C_keep → C_drop aliases → C_drop name）
2. aliases 去重
3. canonical 不进入 aliases
4. chunk_ids union
5. mention_count = len(union)，同 chunk 只 +1
6. chapters union
7. C_drop relationship 重定向
8. 重定向后相同关系合并（chunk_ids 并集 / confidence 重聚合 / evidence cap）
9. self-loop 删除
10. C_keep Person.id 保持不变
11. C_drop 被删除
12. search alias 仍命中 C_keep

**集成**：
- 构造最小 A/B + bridge mention 图，跑完整 b1+b2（mock judge）→ 验证最终 Neo4j 状态：无 C_drop 节点、边正确、search 命中 C_keep、id 稳定

---

## 5. 职责边界（resolver / merger / db）

| 层 | 职责（b1：纯 decision，只读 resolver） | 职责（b2：应用 merge_map，唯一改状态处） |
|---|---|---|
| **resolver.py** | 新增：established 快照、bridge evidence 旁路收集、first_seen_chunk / mention_count / chapters 轻量状态（只读附加，不改 known/_index/canonical_aliases）、merge judge 调用、merge_map 构建 + `resolve_merge_root` | 提供 merge_map + 更新后的 canonical_aliases 给 apply_aliases（b2 才允许更新 alias 结构） |
| **merger.py** | 不变 | PersonAgg 加 `chunk_ids`（merge_extractions 同步收集）；新增 `apply_merges(graph, merge_map)`：PersonAgg 合并、aliases 合并、RELATES_TO 重定向/聚合/self-loop 删除（**唯一应用 merge_map 处**，只读 graph 内 aliases） |
| **db/neo4j.py** | 不变 | `upsert_graph(novel_id, merged, merge_map)` 扩展：内部 `session.execute_write(unit_of_work)` 单事务（C_keep update → 边 upsert → C_drop DETACH DELETE） |
| **schemas/llm.py** | 新增 MergeJudgeResult / MergePair 契约 | 不变 |
| **llm_client.py** | 新增 `judge_merges(pairs)`（复用 429/5xx 重试模式） | 不变 |
| **novels.py** | `_run_ingest` 接线：resolve → b1 → stats | 接线（已确认 2026-08-23）：`resolve` 全部 chunks → `resolver.decide_merges(llm_client.judge_merges, threshold)` → `merge_extractions(resolved)` → `apply_aliases(merged, canonical_aliases)` → `apply_merges(merged, merge_map)` → `db.upsert_graph(novel_id, merged)`；merge stats（candidate/merged/rejected/failed）写入 job stats，merge_failures 不进 failed_blocks |

## 6. merge_map 生命周期

1. b1 构建（ingest 内，resolver 实例内存；**b1 不修改 resolver 任何状态**）
2. b2 应用（内存 MergedGraph 合并 + 落库；**merge_map 只在 b2 被消费**）
3. ingest 结束 → resolver 实例丢弃；canonical 结果已落库，merge_map 不持久化
4. 旧 Novel 数据不迁移（明确不做）

## 7. error handling 汇总

| 环节 | 失败行为 |
|---|---|
| merge judge LLM 调用失败 / 校验失败 | 不 merge；计入 `stats.entity_resolution.failed_pairs` + `merge_failures`；不写 failed_blocks |
| confidence < 阈值（可配置 `merge_confidence_threshold`，默认 0.5，非硬编码） | 不 merge；计入 rejected_pairs |
| 批量中部分 pair 失败 | 只 merge 成功的 |
| b2 单事务失败 | 整体回滚；job failed |
| 传递冲突（A≈B, B≈C） | 不自动合并；除非 A/C 有独立 evidence 且 judge 通过 |

## 8. 本阶段明确不做（YAGNI）

- Embedding / Vector DB / Global clustering
- 全局 canonical pair comparison（O(N²)）
- 自动传递闭包合并（union-find）
- canonical 重命名 / 重选
- 旧 Novel 数据迁移
- 前端 / GraphResponse / API 修改

## 9. 潜在风险（修订后）

1. **merge judge 非确定性（P06 域）**：同 pair 跨运行可能判不同 → 多次评估取趋势；evidence 带原文 + confidence 阈值保守
2. **错误合并不可逆**：judge 误判 → 数据错误。缓解：失败/低置信默认不 merge；b2 单事务可回滚
3. **mention_count 语义**：必须给 PersonAgg 加 chunk_ids（merger 必要改动），否则同 chunk 重复计数
4. **不做传递闭包**：极端情况同一人多组分裂（A≈B、B≈C 各自有 evidence 但 A/C 无）会留下中间态——接受，由独立 evidence 逐步收敛
5. **旧库不自动修复**：仅作用于 ingest 时；如需修复 765a7a13 需单独脚本（范围外）
6. **b1 轻量统计准确性**：resolver 侧 mention_count/chapters 为近似的 distinct chunk 统计（与 merger 最终聚合口径一致即可；b2 以 PersonAgg.chunk_ids 为准）

## 10. 测试策略总览

- **b1 测试**：11 项（§3.8），mock merge judge
- **b2 测试**：12 项单测 + 1 项集成（§4.8），mock merge judge
- 全部遵守 TESTING.md §9（真实 LLM 与 pytest 分离）；不调用真实 LLM
- 新增测试文件建议：`backend/tests/unit/test_merge.py`（b1+b2 单测）、`backend/tests/integration/test_merge_neo4j.py`（b2 集成）
