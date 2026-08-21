# V0.2 第一步：人物实体消歧（Alias / Entity Resolution）— 设计文档

- 日期：2026-08-21
- 状态：已评审定稿（含用户 8 条修正 + 3 条实现级约束）
- 唯一业务目标：Entity Resolution。不引入 Embedding / Vector DB / 全局聚类 / Event / Timeline / GraphRAG / 新前端业务功能。

## 1. 范围红线

- 已有 extract（并发抽取）、merge（按名聚合）、Graph API、前端 UI 行为**保持不变**。
- 只扩展：`Person.aliases[]` 属性、人物搜索的 alias 匹配、抽取与合并之间新增的实体消歧环节。
- 不写死小说人物知识到 Prompt（禁止「看到二老请判断为傩送」）——系统只能靠 当前 chunk + 候选 + LLM 判定，实测报告是消歧质量的真实度量。

## 2. 数据模型

**Neo4j Person（扩展）**：

```
Person { id: uuid, novel_id, name, aliases: [str], mention_count, chapters }
```

- `name` = canonical 主名；`aliases` = 确认的别名（**不含 canonical 自身**、去重、按首次确认顺序）。
- 约束不变：`UNIQUE(Person.id)`、`UNIQUE(Person.novel_id, Person.name)`；**alias 不建独立节点**。

**mention_count 语义（与 V0.1 一致）**：canonical 人物（含其全部 alias 的提及）出现在 characters 字段的 **distinct chunk 数**；同一 chunk 出现 二老/傩送/二老 → `+1`（非 +3）；aliases 不影响计数（resolver 替换为 canonical 后天然合并）。

## 3. 管线与生命周期

```
_run_ingest:
  resolver = EntityResolver()                        # 一次 ingest 一个实例（known/mention index 整本持续）
  extractions = extract_all(...)                     # 并发抽取（不变）
  resolved = []
  for chunk, result in sorted(extractions, key=chunk_id):   # 按 chunk_id 升序，顺序稳定
      resolved.append((chunk, resolver.resolve(chunk, result)))
  merged = merge_extractions(resolved)               # 不变，canonical 名聚合
  db.upsert_graph(novel_id, merged)                  # 写入 aliases
```

**生命周期硬约束**：`known` / `canonical_aliases` / mention index 在整本小说处理期间持续存在；禁止每个 chunk 新建 resolver（否则「与已有人物候选匹配」失去意义）。

## 4. EntityResolver 算法（`pipeline/resolver.py`）

状态：
- `known: dict[str, str]`：名字 → canonical（含 canonical 自身与全部 alias）
- `canonical_aliases: dict[str, list[str]]`：canonical → 别名（保序）
- mention index：`canonical → matched_names: set`（canonical + 全部别名，去重后按人物分组，候选不膨胀）

`resolve(chunk, result) -> ExtractionResult`，对 characters **按原始出现顺序**处理、关系端点同样走统一 `_resolve_name`：

```
读取 chunk result
  ↓
对 characters 按出现顺序逐个处理：
  ├─ 精确命中 known            → 立即替换为 canonical
  ├─ 无候选                     → 立即成为新 canonical，更新 known/index（不调 LLM）
  └─ 有候选（简单召回）          → 收集进本 chunk 的 pending 列表（不立即判定）
  ↓
chunk 末尾：pending 非空 → 一次 judge_aliases(chunk_text, pending)
  ↓
统一应用结果 → 更新 known / index
```

**更新时机固定**：规则确定（精确命中 / 无候选新 canonical）立即更新；LLM 判定结果在 chunk 末**统一应用**。禁止「二老→LLM→更新→大老→LLM→更新」的逐名调用（每 chunk 至多一次 judge 调用）。

**canonical 规则（写死）**：实体组按 chunk 顺序**首次出现且通过确认**的 mention 定为主名；后续确认的名称全部追加为 alias；**不重新选择 canonical**。LLM 判 `null`（有候选但非同一人）→ 该 mention 独立成为新 canonical，**不做第二轮判定**（防止循环）。

## 5. 候选召回（无 embedding）

- 对未知 mention，与 mention index 中全部人物（canonical+aliases 去重后）计算**共享字符数**，子串包含关系优先，取 top-k（默认 5）。
- 召回返回按 canonical 分组去重：`{mention, candidates: [{canonical, matched_names}]}`——同一人物只出现一次。
- 全量遍历（本书规模可接受）；召回只求「别漏」，精度交给 LLM 判定。

## 6. judge_aliases 契约

调用：`llm_client.judge_aliases(chunk_text, pending: list[PendingMention]) -> AliasJudgeResult`，JSON mode + Pydantic 校验。

```json
{ "resolutions": [{ "mention": "二老", "resolves_to": "傩送" | null }] }
```

**6 条约束（schema + resolver 双层校验）**：
1. `mention` 必须来自输入 mentions
2. `resolves_to` 必须是 `null` 或候选 canonical
3. 禁止生成输入之外的新人物名
4. 不得修改 mention
5. 每个 mention 最多一条 resolution（重复则取首条 / 拒绝）
6. 失败分类沿用现有：429/5xx 重试 1 次；validation error 不重试

## 7. 失败与状态（解析阶段警告 ≠ ingest 失败）

- 单 chunk 判定失败（validation error / 重试后仍 429/5xx）：本 chunk 全部待判定 mention **独立成为 canonical**，记录 `failed_blocks` 条目 `{chunk_id, chapter_id, error: "alias_resolution_failed"}`，**继续后续 chunk**。
- Job 最终状态：只要抽取或消歧存在失败块 → `completed_with_errors`（**不是 failed**）；用户可见「小说已分析完成，部分实体消歧失败」。
- **预期行为（非 bug）**：判定失败时本来应合并的 二老/傩送 可能暂时成为两个 Person；代码与测试明确标注。

## 8. merger / 写层适配

- `PersonAgg` 增加 `aliases: list[str]`；`merge_extractions` 聚合时合并各 canonical 的别名（去重、保序、**排除 canonical 自身**：`alias == canonical → ignore`）。
- `upsert_graph`：Person MERGE（by novel_id+name）后 `SET p.aliases`。
- **搜索扩展**：`search_characters` Cypher 改为 `p.name CONTAINS $q OR ANY(a IN p.aliases WHERE a CONTAINS $q)`——用户搜「二老」返回「傩送」；前端与 Graph API 零改动（UI 不需要知道 alias 存在）。

## 9. 测试（test_resolver.py 至少锁死以下 6 + 1 回归）

1. 新名字 + 无候选 → 新 canonical → **不调用 LLM**
2. 新名字 + 候选 → **每 chunk 只调用一次 judge_aliases**
3. LLM 判定 alias → 指向已有 canonical → alias 加入 → canonical 不改变
4. LLM 返回 null → 新 canonical → **不进行第二轮判定**
5. LLM validation 失败 → 待判定名字独立 canonical → failed_blocks 记录 → 后续 chunk 继续
6. 同一实体多个 alias → aliases 去重 → 首次确认顺序 → canonical 不进入 aliases
7. **回归（首次出现定主名）**：
   - Chunk1: 二老 / Chunk2: 傩送 → `canonical=二老, aliases=["傩送"]`
   - Chunk1: 傩送 / Chunk2: 二老 → `canonical=傩送, aliases=["二老"]`

另：test_merger.py 增加 aliases 聚合用例；集成测试上传含 二老/傩送 的《边城》片段验证 Person.aliases 与图合并。

## 10. 已知限制（V0.2 声明）

- LLM 判定概率性：同一小说重跑 aliases 可能微差（可接受）。
- 判定失败副作用：可能临时出现本应合并的两个 Person（预期行为）。
- 无 embedding：仅字符召回 + LLM 判定；《边城》实测后决定是否引入向量召回。
