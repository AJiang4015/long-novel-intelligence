# 项目技术知识地图 v1（Technical Knowledge Map）

> 用途：**技术接管 / 源码理解 / 面试化准备**的导航文档（CODE FREEZE 后，研发阶段结束）。
> 依据：当前仓库 HEAD（`1bbc40a`，tests=350 passed，CODE FREEZE 状态）。
> 配套：`ARCHITECTURE.md`（系统组织）、`DECISIONS.md`（D-1..D-19）、`PROBLEM.md`（P01-P21）、各 `*_LAYER.md`（层契约）、`TESTING.md`（验证规范）、`docs/ROADMAP.md`（收口路线图）。

---

## 0. 一页总览

```text
┌─ Frontend（React + Vite + TS）────────────────────────────────────────┐
│ App.tsx 阶段机 empty→processing→graph；job 轮询；GraphCanvas(SVG)      │
└───────────────┬──────────────────────────────────────────────────────┘
                │ REST（/api/...，Vite dev proxy → FastAPI）
┌─ Backend（FastAPI，单进程）───────────────────────────────────────────┐
│ api/novels.py _run_ingest（BackgroundTasks 后台 job）                  │
│   pipeline：epub_reader→sections→chunker→extractor(LLM)→hygiene→       │
│             resolver(recall→judge→admission→registration)→merger→db   │
│   checkpoint/（P19：durable recovery state，默认开）                   │
│   db/neo4j（最终图唯一权威）│ models/job（进程内 execution handle）      │
│ tools/eval_framework（P20：可重复 regression evaluation）              │
└───────────────┬──────────────────────────────────────────────────────┘
                │ bolt://（novel-neo4j 容器，5.26 Community）
        Novel / Person / RELATES_TO（novel_id 双层隔离，D-3）
```

| 层 | 模块 | 一句话职责 |
|---|---|---|
| api | novels / characters / jobs / health | HTTP 边界、DTO、ingest 编排、job 暴露 |
| pipeline | epub_reader→sections→chunker→extractor→hygiene→resolver→merger→lineage | 抽取→消歧→合并→观测全链路 |
| checkpoint | store | P19 durable checkpoint 文件 I/O（纯 I/O，无业务决策） |
| db | neo4j | novel_id 隔离读写、单事务写最终图、delete_novel |
| models | job | 进程内 JobStore 状态机 |
| schemas | api / llm | 跨层契约（DTO / MentionCategory / ExtractionResult…） |
| tools/eval_framework | checks / runner / evidence / baseline / report | P20 可重复 regression evaluation |
| frontend | App / api / components | 上传→轮询→图展示（SVG） |

---

## 1. 完整系统架构

- 依赖方向（ARCHITECTURE §3，**有向无环**）：
  `main.py → api → {pipeline, db, models, schemas, config, checkpoint}`；`pipeline → {schemas, config}`；`schemas → models`；`db → neo4j driver`；`checkpoint → stdlib only`；`tools/eval_framework → app（经 TestClient/import）`。
  **禁止反向**：pipeline/db/models 不 import api；db/models 不 import pipeline；pipeline 不碰 HTTP/Neo4j。
- 关键边界：api 不做 ER 判定；pipeline 不持久化（Neo4j 只经 db）；db 不做业务决策；checkpoint 不判兼容（归 api）；lineage 纯旁路 observer（D-8）。
- 部署：backend（uvicorn）+ frontend（Vite）+ novel-neo4j 容器（独立卷 `novel_neo4j_data`，与共享 VM 其他项目隔离）。

## 2. ingest 主链路（novels.py `_run_ingest`）

```text
POST /api/novels（multipart EPUB ≤50MB）
 → novel_id=uuid4 / job_id（P19：重传同文件+同指纹 → 复用 novel_id，续跑/幂等）
 → read_epub       → list[Chapter]（chapter_id 1 起；section 已分类）
 → chunk_chapters  → list[Chunk]（CHUNK_SIZE=4000 / OVERLAP=400；chunk_id 全局递增）
 → extract_all     → ExtractionBundle{results, failed}（ThreadPoolExecutor，并发 LLM）
 → EntityResolver.resolve ×N（chunk_id 升序，整本一个实例）
 → merger：merge_extractions → apply_aliases → decide_merges（一次 batch merge judge）→ apply_merges
 → finalize / drop_unconfirmed_entities（provisional flush）
 → db.upsert_novel + db.upsert_graph（Neo4j 单事务）
 → job_store.update 终态（completed / completed_with_errors / failed）+ lineage flush
```

**LLM 调用点（全部 token 成本）**：`extract_chunk`（每 chunk）、`judge_aliases`（每 chunk 至多一次，输入含整块 chunk 正文）、`judge_merges`（末尾一次 batch）。
**确定性**：chunk_id 升序处理 + first-seen 锁定 + 稳定排序 → 同输入可逐字节重放（P19 复用此性质做 judge 重放）。

## 3. extraction → recall → judge → resolver → merge 主链路（ER 核心）

归因链（PIPELINE_LAYER §4，六类失败互斥）：`extraction coverage ≠ recall ≠ judge ≠ admission ≠ registration ≠ merge`。

| 层 | 模块/函数 | 输入 | 输出 | 失败形态 |
|---|---|---|---|---|
| extraction | extractor.extract_one / llm_client.extract_chunk | chunk 正文 | ExtractionResult{characters[+category/roles], relationships} | 未提取（D5-a coverage）、类别错标（D5）、形状不合规（validation） |
| hygiene | hygiene | mention + category | COLLECTIVE/INVALID 硬滤、GENERIC 精确词表（其余 None） | 误伤（词表项目级规则，D-15） |
| recall | resolver（chunk 预扫描 + known/_index） | 提取结果 + 既有 known | 候选集（≤RECALL_TOP_K=5；同 chunk 共现 / 文本重合 / 强提取） | 零候选（P08 分裂）、顺序敏感（P10 已修：预扫描） |
| judge | resolver._judge → llm_client.judge_aliases | chunk 正文 + pending mentions | AliasJudgeResult{resolves_to \| null \| missing} | 非确定性（P06）、判 null |
| admission | resolver（role gate D-5 / provisional D-9 / deferred D-17） | judge 结果 + 上下文 | confirmed / alias / unresolved / dropped / blocked | 误吸（P16-b/P18，已冻结）、碎片注册（P17） |
| registration | resolver._register / _add_alias | 准入结果 | canonical 首现锁定、aliases 保序去重、mention_count=distinct chunk | 碎片（D-9 已修：unresolved 不注册） |
| merge | resolver.decide_merges（b1 纯决策）→ merger.apply_merges（b2 应用） | canonical 快照 + 桥接证据 | merge_map（C_drop→C_keep） | judge 失败/超限（6MB 已修）、误合并（P08） |

## 4. Neo4j 数据模型

- 节点：`Novel{id, title, chapters[]}`、`Person{novel_id, name, aliases[], mention_count, chapters[], id(uuid)}`；
- 关系：`(:Person)-[r:RELATES_TO{novel_id, source, target, type, weight, confidence, evidence[]}]->(:Person)`；
- 唯一约束：`person_novel_name (novel_id, name)`（D-2 身份模型）；
- **隔离铁律**：只 Novel/Person/RELATES_TO；跨 novel 查询/清理禁止；删除一律 `db.delete_novel(novel_id)`（D-3 / AGENTS §2）；
- Neo4j = **最终图唯一权威**（checkpoint 是中间态，前端只是读）。

## 5. FastAPI / job 生命周期

- `create_app()`（main.py）+ lifespan：settings（lru_cache）/ Neo4jDB / JobStore / LLMClient 注入 `app.state`；
- 上传 → `BackgroundTasks` 跑 `_run_ingest`（非阻塞请求）→ 前端轮询 `GET /api/jobs/{id}`；
- Job 状态机：`pending → running → completed / completed_with_errors / failed`（models/job.py JobState + JobStore 进程内锁）；
- **P19 分层（D-18）**：job_id = 执行实例（进程内，D-14 不复活）；novel_id = 小说身份（可复用）；**checkpoint = durable recovery state**；
- 已知限制：进程重启后旧 job_id 消失（D-14）；前端 `ExistingNovelPicker` 用 `GET /api/novels` 探测恢复。

## 6. React graph 查询与展示

- `api.ts`：uploadNovel / getJob / getNovel / listNovels / searchCharacters / getGraph（统一 handle：非 2xx 抛 detail）；
- `App.tsx` 阶段机：`empty → processing → graph`（failed → ErrorBanner 保留 job 错误）；processing 期间 `setInterval` 轮询 getJob，终态后 getNovel；
- 图：点击人物 → `getGraph(character_id)` → `GraphResponse{nodes, edges}`（1-hop 子图）→ `GraphCanvas` 自绘 SVG（力导向简化布局）；`CharacterSearch` 走 `searchCharacters?q=`；`DetailsPanel` 展示选中边 evidence（chunk/chapter/text）；
- 前端不直接碰 Neo4j，全部经后端 API（双层隔离 novel_id + character_id）。

## 7. checkpoint / failure handling（P19，D-18）

- 目录：`checkpoints/{novel_id}/{manifest.json, chunks.jsonl, extraction/{cid}.json, judge/{cid}/{input_fp}.json, merge_judge/{fp}.json}` + 复合索引 `index.json{content_hash:config_fingerprint→novel_id}`；
- 指纹（§5）：content_hash=文件身份 / config_fingerprint=配置身份（schema/chunking/extractor/prompt×3/model/chunk/overlap）/ structure_hash=chunking integrity / judge input_fingerprint（canonical serializer，**不绑定 chunk_id alone**）；
- manifest 两态 `IN_PROGRESS/COMPLETED`；COMPLETED 准入 = 无缺口 + 写库成功；job 终态与 manifest 解耦；
- ReplayJudge/ReplayMergeJudge：命中兼容 checkpoint → 重放零 LLM；miss → 真调并持久化；judge 失败不落盘 = 可重试；
- 失败分类：extraction 429/5xx 重试 1 次、validation 不重试；judge 失败 fail-safe 不落盘；merge 失败记 failed_pairs；checkpoint 写失败降级（不浪费 LLM 工作）；
- **默认开**（er_checkpoint_enabled=True）；eval 强制 False（fresh novel，G5 守卫）。

## 8. evaluation framework（P20，checkset v2）

- 模块：`checks.py`（checkset v2 24 条 A1-A7+B-G + 纯函数判定）、`runner.py`（事实采集，CLI `--runs/--smoke/--dry-run`）、`evidence.py`（alias→原文上下文）、`baseline.py`（聚合/分类/validity/compare）、`report.py`（TESTING §9 渲染）；
- 判定分类：`PASS/FAIL/OBSERVATION/INCONCLUSIVE/SKIP`（决定性 = PASS/FAIL；OBSERVATION 记录不判败；INCONCLUSIVE 证据缺失；SKIP 前置不满足防空洞 PASS；G4：失败 chunk → 依赖全语料检查 INCONCLUSIVE）；
- 经验分类：stable/variance 只描述稳定性不描述 correctness（决定性结果全同=stable 含 stable failure；混合=variance）；**初判 outcome_class 仅展示不参与分类**；
- baseline validity：stable failure → `INVALID_NOT_REGRESSION_SAFE`，禁止正常回归比较；compare 兼容性唯一依据 = compare_identity（git_commit 仅 provenance）；
- **当前事实**：v1 基线 INVALID（A1，已 D-19 收敛）；v2 基线 INVALID（**C3 stable failure**，hard gate 保留）；`--establish-baseline/--compare-baseline` CLI 未接（纯函数接口可用）；
- 检查集 v2 要点：A1 核心 gate（傩送/二老）、A7 老二 观察（D-19）、C1/C2/C4 P16-b 系、C3 爹爹 hard gate（P017 D5-a）、F1 merge 观察（6MB 修复后恢复可判定）。

## 9. P16～P21 演进关系（叙事）

```text
P16 非正文污染（题记→canonical 首现）→ P16-a 已解决（sections 分类 + provisional/promotion/flush）
P16-b 正文角色称谓 sink（父亲→顺顺 吸收）→ 单独立项 P018；D-5 evidence gate 冻结（D-6）
P17 DESCRIPTIVE 碎片化 → B1 deferred + D-9 unresolved 不注册 + D-5-b（generic+judge-null 不注册）；
      D5-a（extraction coverage）Known Limitation（爸爸/妈妈/大儿子/翠翠的祖父/**爹爹**）
P18 即 P16-b（合并进 D-5/D-6 冻结语义）
P19 ingest 不可恢复 → checkpoint/resume（D-18）实现 + 真实评估
P20 人工验收不可重复 → Evaluation Framework（checkset v2 + 基线 + validity）实现；基线 INVALID（诚实输出）
P21 老二 漏提（A1 稳定失败）→ lineage 归因 EXTRACTION_LAYER → D-19 产品边界（单次低显著性不要求覆盖）收敛
C3 爹爹（P017 D5-a 实例）→ lineage 归因 EXTRACTION_LAYER → hard gate 保留，Known Limitation
merge 6MB → MERGE_EVIDENCE_CAP=5 修复（1bbc40a，CODE FREEZE 前最后一笔）
```

## 10. 核心模块文件/类/函数索引

| 模块 | 文件 | 类/函数（关键） | 职责一句话 |
|---|---|---|---|
| epub | `pipeline/epub_reader.py` | `read_epub` / `Chapter` | EPUB→章节（含 sections 分类） |
| sections | `pipeline/sections.py` | `classify_chapter` / `SectionType` | METADATA/EPIGRAPH/BODY/TRAILER 启发式（D-16） |
| chunker | `pipeline/chunker.py` | `chunk_chapters` / `Chunk` / `CHUNKER_VERSION` | 按 4000/400 切块，chunk_id 全局递增 |
| llm | `pipeline/llm_client.py` | `LLMClient.extract_chunk/judge_aliases/judge_merges` + 6 个 prompt 常量 | 三处 LLM 调用 + 失败分类 + 重试 |
| extractor | `pipeline/extractor.py` | `extract_one/extract_all` / `EXTRACTOR_VERSION` / `ExtractionBundle` | 并发抽取编排 + on_chunk_result 钩子（P19） |
| hygiene | `pipeline/hygiene.py` | 分类函数 / `_RELATIONAL_GENERIC_WORDS` | COLLECTIVE/INVALID/GENERIC 精确硬滤（D-15） |
| resolver | `pipeline/resolver.py` | `EntityResolver.resolve/decide_merges/finalize/_resolve_name` / `RECALL_TOP_K` / `MERGE_EVIDENCE_CAP` | 整本消歧：recall→judge→admission→registration→merge 决策 |
| merger | `pipeline/merger.py` | `merge_extractions/apply_aliases/apply_merges/drop_unconfirmed_entities` / `EVIDENCE_CAP=5` | 跨 chunk 聚合 + b1 决策应用（b2） |
| lineage | `pipeline/lineage.py` | `LineageRecorder` / `create_lineage_recorder` | P06 观测旁路（D-8），job 终态 flush JSONL |
| checkpoint | `checkpoint/store.py` | `CheckpointStore`（put/get_exact/exists/delete/list/find_manifest/rebuild_index） | P19 durable checkpoint 纯 I/O |
| db | `db/neo4j.py` | `Neo4jDB`（upsert_novel/upsert_graph/count_stats/search_characters/get_subgraph/delete_novel） | novel_id 隔离读写 + 单事务写图 |
| models | `models/job.py` | `JobState/JobStatus/JobStore`（create/get/update/get_or_create_running_job） | 进程内 job 状态机（P19 TOCTOU 闭合） |
| schemas | `schemas/api.py` `schemas/llm.py` | DTO + MentionCategory/ExtractionResult/AliasJudgeResult/MergeJudgeResult/MergePair | 跨层契约 |
| api | `api/novels.py` | `create_novel/_run_ingest/ReplayJudge/ReplayMergeJudge/_config_fingerprint` | 编排 + 指纹 + 幂等/续跑 |
| eval | `tools/eval_framework/*` | `CHECKSET_V2 / evaluate_checkset / aggregate_runs / compare_run / run_report…` | P20 评估（见 §8） |
| frontend | `src/api.ts` `src/App.tsx` `src/components/*` | uploadNovel/getJob/getGraph；phase 机；GraphCanvas | 上传→轮询→图展示 |

## 11. 核心数据结构（I/O 契约速查）

- `Chapter{chapter_id, chapter_title, text, section_type}`；`Chunk{chunk_id, chapter_id, chapter_title, text, start_offset, end_offset, section_type}`；
- `ExtractionResult{characters:[{name, category?, roles?}], relationships:[{source, target, type, confidence}]}`；
- `PendingMention{mention, candidates:[AliasCandidate{canonical, matched_names}]}`；`AliasJudgeResult{resolutions:[{mention, resolves_to}]}`；
- `MergePair{a: MergePairSide{canonical, aliases, first_seen_chunk, mention_count, chapters}, b: …, bridge_evidence:[BridgeEvidence{chunk_id, chapter_id, mention, text}]}`；`MergeJudgeResult{merges:[{a, b, merge, confidence}]}`；
- `PersonAgg{name, mention_count, chapters, aliases, chunk_ids}`；`MergedGraph{persons, relationships}`；
- checkpoint manifest / run result.json / baseline artifact（见 P19/P20 文档 §5）。

## 12. 关键设计为什么（决策速查）

| 设计 | 为什么 | 决策 |
|---|---|---|
| canonical 首现锁定，不重选 | 确定性 + 重放稳定（P08 first-seen） | D-4 |
| b1 纯决策 / b2 应用分离 | 避免半合并状态、可测试 | D-13 |
| mention_count = distinct chunk | 明确可断言语义 | D-4 / TESTING §4 |
| hygiene 只做高置信硬滤 | 语义分类留给 LLM，避免规则误伤 | D-15 |
| sections 项目级启发式 | 确定性优先；词表换语料需重评 | D-16 |
| lineage 默认关 + 旁路 | 观测零侵入（判定路径逐字节不变） | D-8 |
| checkpoint 双层 + 指纹 | 已完成阶段零重复 LLM；语义相关才作废 | D-18 |
| job 进程内 / checkpoint durable | 避免 Redis；Job 是 handle，Checkpoint 是恢复态 | D-14/D-18 |
| stable/variance 与 correctness 解耦 | 稳定失败 ≠ variance；诚实暴露质量缺口 | P20 v1.1（用户拍板） |
| MERGE_EVIDENCE_CAP=5（独立于 EVIDENCE_CAP） | 语义不同（桥接 vs 关系证据）；确定性前 N 条防 6MB | 1bbc40a |
| D-19 单次低显著性不要求覆盖 | 产品验收边界；防为单次 mention 增加复杂度 | D-19 |

## 13. 当前 Known Limitations（面试诚实清单）

1. **P017 D5-a extraction coverage**：爸爸/妈妈/大儿子/翠翠的祖父/**爹爹** 等角色称谓/低显著性 mention 在 deepseek-v4-flash 下漏提（EXTRACTION_LAYER）；C3 保持 hard gate；不修（需求触发再议）；
2. **v2 baseline INVALID**（C3 stable failure）——回归比较门禁不可用；INVALID 是框架如实工作的证据，非缺陷；
3. **merge 大语料余量**：6MB 已修（CAP=5，当前 2.6× 余量）；pair 数显著扩大时需按字节/令牌分桶 batch（暂不实现）；
4. **judge 串行瓶颈**：resolver 跨 chunk 有状态 → 不能并发（确定性）；单 run ~13 分钟（并发 4）；
5. **checkpoint 需重传同一文件**（不持久化 epub）；进程重启 job_id 丢失（D-14）；
6. **merge_judge 判定为模型输出**：c3 类 run 中 judge 拒绝对多（48/51）属模型行为，非算法缺陷；
7. **语料锁《边城》**：词表/分类/检查集均为项目级规则，换语料需重评（D-7/D-16）；
8. **单次真实评估不构成结论**（P06）：趋势需多次运行或基线比较。

## 14. 面试追问点（按模块，第四阶段逐模块展开）

- **总体**：为什么用 Neo4j？novel_id 双层隔离怎么做？一次 ingest 的 token 成本构成？
- **chunking**：4000/400 怎么来的？overlap 意义？chunk 边界对 ER 的影响（P10 顺序敏感）？
- **ER**：怎么消歧？canonical 首现为何不重选？零共享字别名（天保↔大老）如何召回？judge 非确定性如何治理（lineage/趋势）？为什么 judge 不能跨 chunk 并发？
- **role gate（P16-b）**：qualified 与 bare 判定？≥2 独立证据？为什么冻结？为什么不能扩 generic 词表（D-7）？
- **merge**：b1/b2 为什么分离？桥接证据是什么？6MB 根因与修复权衡？EVIDENCE_CAP 与 MERGE_EVIDENCE_CAP 为何独立？
- **checkpoint（P19）**：为什么 job 与 checkpoint 解耦？指纹体系？幂等重传？写失败降级？
- **评估（P20）**：为什么基线 INVALID 是好事？stable/variance 与 correctness 解耦？REFUSE_COMPARE 何时触发？
- **性能**：judge 串行瓶颈根因（resolver 状态）？extract 并发？token/时延/成本模型？
- **工程**：测试纪律（350 unit+integration 分离、真实评估纪律）；数据安全（delete_novel、禁止全库删）；lineage 旁路为什么零侵入。

---

*本地图为 v1 快照；第四阶段按「现状→数据流→设计原因→trade-off→失败模式→面试问题→你回答→纠错」逐模块展开。*
