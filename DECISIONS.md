# DECISIONS.md — 已做出的架构 / 工程决策记录

> 定位：**已经决定了什么、为什么**。这是 Decision Record，**不是**问题记录（→ `PROBLEM.md` / `docs/problems/`），**不是**实现说明（→ `*_LAYER.md`），**不是**实验过程（→ `docs/evaluation/`）。
>
> 新增长期决策时在此登记；**不要把单次实验结论升级为永久 Decision**（实验结果先入 `docs/evaluation/`，形成稳定决策后再登记）。
> 决策的状态：`Accepted`（现行有效）/ `Frozen`（已验证并冻结，不再修改）/ `Superseded`（被新决策取代，保留历史）。

## 决策模板

```text
## D-XX — <Title>
- Status: <Accepted / Frozen / Superseded>
- Date: <记录日期>（决策形成于 <版本/阶段>）
- Context: 为什么出现这个决策（背景、约束、事故）
- Decision: 决定做什么 / 不做什么
- Reason: 为什么这样决定（关键权衡）
- Consequence: 后果 / 影响 / 后续约束
```

---

## D-1 — EPUB 作为输入格式

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.1 项目起始）
- **Context**: 长篇小说输入源需统一；项目面向中文网络文学/公版小说，EPUB 为常见可解析格式（`ebooklib` 解析，含章节结构）。
- **Decision**: 系统输入格式固定为 EPUB；上传接口仅接受 `.epub`（≤50MB），非 epub 文件拒绝（400）。
- **Reason**: 有现成解析链路（`epub_reader` → chapters）与稳定结构（标题/正文可分）；避免多格式适配成本。
- **Consequence**: 后续格式支持（如 TXT/MD）需作为独立决策立项；解析契约（chapters 结构）由 `pipeline/` 与 `SCHEMA_LAYER.md` 约束。

## D-2 — novel_id + canonical identity 模型

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.1 身份模型 + V0.2.3 canonical merge）
- **Context**: 多人共用同一 Neo4j 实例，且 ER 需要跨 chunk 保持实体身份；人物消歧后 canonical 需要稳定标识。
- **Decision**: 每个上传 Novel 生成独立 `novel_id`；Person 身份 = `(novel_id, name)` 唯一（Neo4j 唯一约束 `person_novel_name`），内部 `id` 为 uuid。canonical 由 resolver 整本持续维护（`known` / `canonical_aliases` 跨 chunk 累积），canonical 首现定主名后不重选。
- **Reason**: novel_id 隔离保证多小说数据互不污染（P01/P02 事故教训）；canonical 首现锁定保证确定性（P08 first-seen locking）。
- **Consequence**: 所有查询/清理必须带 novel_id（双层隔离）；别名/mention 统计语义（mention_count = distinct chunk）由 `TESTING.md` 固化；跨 novel 操作被禁止（`AGENTS.md` §2）。

## D-3 — Person / RELATES_TO 数据模型边界

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.1 + P02 事故后强化）
- **Context**: 曾发生共享 Neo4j 实例混入约 4.8 万医疗节点（P02）；测试曾全库删除留下 329 孤儿 Person（P01）。
- **Decision**: 小说项目数据库只负责 `Novel` / `Person` / `RELATES_TO` 三种结构；使用独立 `novel-neo4j` 实例与共享栈完全隔离；严禁触碰其他标签/实例/数据。
- **Reason**: 数据安全优先；共享实例混入 + 无范围删除已造成真实事故。
- **Consequence**: 任何数据删除必须按 novel_id 精确执行（`db.delete_novel`）；`AGENTS.md` §2 固化禁止项；新增标签/关系类型需独立设计决策。

## D-4 — canonical / alias 策略

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.1-V0.2.3 演化）
- **Context**: 同名/别名消歧（零共享字别名如 天保↔大老、傩送↔二老）需要稳定 canonical 命名与 alias 语义。
- **Decision**:
  - canonical 首现定主名，不重选（first-seen locking）；
  - aliases 保序、去重、不含 canonical 自身；
  - mention_count = canonical+别名出现在 characters 字段的 distinct chunk 数；
  - `EntityResolver` 一次 ingest 一个实例，`known`/mention index 整本持续；
  - canonical merge 采用 b1 决策（纯内存）→ b2 应用（单事务写库）分离。
- **Reason**: 确定性优先（重放结果稳定）；合并决策与应用分离避免半合并状态（P08/P10 教训）。
- **Consequence**: 测试锁死这些语义（`TESTING.md` §8）；合并应用不在 resolver 内改写 known（D-13）。

## D-5 — P16-b role admission evidence gate

- **Status**: Accepted
- **Date**: 2026-08-27（记录；决策形成于 V0.2.6，2026-08-26 评审 v1-v4）
- **Context**: 正文 relational-role 称谓（父亲/爸爸/爹爹）被 canonical 吸收（P018）；「翠翠的父亲」跨人物错吸风险实证可复现（M5），机制零拦截。
- **Decision**: role alias 证据准入机制——qualified（X的Y）需「target 对齐 + anchor 在场」双条件；bare 需 ≥2 独立证据 → confirmed；observation 永不自动晋升；跨 canonical 冲突 → blocked；触发范围收窄为长辈称谓首字 + category=DESCRIPTIVE 且非 GENERIC。
- **Reason**: 防错优先（语义正确的吸收如 爸爸→顺顺 保留，跨人物错吸如 翠翠的父亲→顺顺 拦截）；v1 的 finalize 兜底被证是 gate 的洞而删除。
- **Consequence**: 父亲 类裸 role 拦截不入图；P16-b 冻结（D-6）；残留 P017 D5 缺口为 Known Limitation（D-10）。

## D-6 — P16-b verified / frozen

- **Status**: Frozen
- **Date**: 2026-08-27（V0.2.6 真实评估验收：mechanism PASS / capability PARTIAL）
- **Context**: V0.2.6 真实评估（job `d002fdec`）确认机制行为符合设计：爹爹→顺顺 confirmed；父亲 不入图；翠翠的父亲 拦截；顺顺 aliases 8→3。
- **Decision**: **P16-b 冻结，不再修改**；残留问题（爸爸 category 缺口 / 翠翠的祖父 观测缺口）分别归 P017 D5（Task B）与 P06（Task A）。
- **Reason**: 机制目标已达成且冻结可避免为个别案例打补丁破坏已验证行为；后续问题有独立立项路径。
- **Consequence**: 任何 P16-b 行为修改需先解除冻结（独立设计 + 评审）；「爸爸 未 confirmed」「翠翠的祖父 未建立」不得作为 P16-b 失败处理。

## D-7 — 不通过扩 generic 词表解决 P016 / P018

- **Status**: Accepted（RC3 已锁）
- **Date**: 2026-08-27（记录；形成于 V0.2.4-b RC3）
- **Context**: 有人提议把 父亲/母亲/祖父 加入 generic 词表以阻止 sink；但它们是《边城》正文真实人物的合法称谓（语义正确吸收），词表化会破坏正向归并。
- **Decision**: **不把「父亲/母亲/祖父」加入 generic 词表**；`_RELATIONAL_GENERIC_WORDS` 只含无争议的关系泛称（兄弟/哥哥/弟弟/儿子/女儿/妻子…）。该词表是**项目级决策，不是通用语义规则**——换小说时需重新评估。
- **Reason**: P016/P018 是 context / relational-role 问题而非词表问题；词表是精确匹配、不子串匹配，误伤风险高。
- **Consequence**: 遇到 父亲→顺顺 类吸收先做 aliases 可解释性核对（P018 Do Not Reopen），不诉诸词表；换小说语料时评估词表边界。

## D-8 — lineage 只允许作为旁路 observer

- **Status**: Accepted
- **Date**: 2026-08-27（V0.2.7 Task A）
- **Context**: 失败无法归层（翠翠的祖父：extraction 未提取 or judge null 无法区分）；需要可观测性但不得改变判定路径。
- **Decision**: lineage 观测 recorder（`LineageRecorder`）默认关闭（`ER_LINEAGE=0` 零开销 no-op）；开启时只记录事件（chunk_start / mention_enter / recall / judge / admission / registration / merge_*），经 `lineage_id` join，job 终态一次性 flush JSONL；**不参与任何业务判定、不 import resolver/merger、不改写任何输出**。离线归层用 `backend/tools/diagnose_lineage.py`。
- **Reason**: 观测必须零侵入（判定路径逐字节不变）；事件先收集后落盘保证确定性。
- **Consequence**: 失败归因优先走 lineage 归层（PROCESS.md §1）；任何让 lineage 参与判定的改动违反本决策。

## D-9 — P017 D2：DESCRIPTIVE/COMPOSITE 无法确认 → unresolved 不注册

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.2.5-b）
- **Context**: DESCRIPTIVE/COMPOSITE 无候选时立即注册 canonical 导致一族碎片（P017：大儿子/长子/次子/第二个儿子）；旧兜底「不静默丢人物」注册（P009 trade-off）被证明制造噪音。
- **Decision**: 无候选 / judge null / judge 缺失 / judge 异常 四路 → **unresolved 不注册**（不进 known/_index/aliases/merge_evidence，输出剔除、关系丢弃、计数）；judge 异常时 PERSON/None 保留既有 fail-safe 兜底注册。
- **Reason**: 消除碎片优先；单次描述性称谓可能不进图是可接受代价（首次信息损失）。
- **Consequence**: `test_hygiene.py:176` 已修订；「DESCRIPTIVE/COMPOSITE 无法确认 → 不注册」是**有意行为**，不是回归（`AGENTS.md` §3）。

## D-10 — 不引入 classifier 绕过 P017 D5

- **Status**: Accepted（约束有效；Task B 已按约束执行）
- **Date**: 2026-08-27（记录；约束形成于 V0.2.5-b，2026-08-26；Task B 执行于 V0.2.8）
- **Context**: D5 是一组「extraction classification 覆盖缺口」，含三个层面：**D5 原义**——category=None → legacy PERSON fallback，使长辈称谓（爸爸/母亲）绕过 B1 与 role gate（P017/P018 实证）；**D5-a**——extraction mention coverage 缺失（爸爸/妈妈/大儿子/翠翠的祖父 等未提取，根本不进入 pipeline）；**D5-b**——LLM generic 标签在 judge-null 路径未生效（母亲 generic + judge null → 仍注册 canonical）。三者均不改变「不引入 classifier」的约束。
- **Decision**: **不擅自补分类器绕过 D5**；D5 修复必须走 归因 → Spec → Review（Task B），且手段不得是引入学习型分类器——允许路径：结构规则对齐 / prompt 增强 / 接受为 Known Limitation。
- **Reason**: 补分类器扩大范围、改变 LLM 契约（MentionCategory 语义）、与「先归因后修改」纪律冲突（D-11）。
- **Consequence**: 执行结果——**D5-b 已按约束以结构规则修复（B-1，V0.2.8，见 D-17）**；**D5-a prompt A/B 已执行，B 未采纳**（extraction coverage 缺失归模型域 P06 提取方差，见 `docs/evaluation/2026-08-27-biancheng-d5a-prompt-ab.md`）；D5 原义（category=None → PERSON fallback）仍为 Known Limitation。任何后续新方案必须先有 Problem Record + Spec + Review（PROCESS.md §5）。

## D-11 — Task A 先于 Task B

- **Status**: Accepted
- **Date**: 2026-08-27（P06 归因链任务编排）
- **Context**: P017 D5 与 P16-b 残留问题缺少观测数据（category 是否落盘、judge 是否调用均未知），直接设计修复会重复「凭经验改代码」。
- **Decision**: **Task A（lineage 可观测性）必须先于 Task B（修复设计）**；先用观测把失败归到具体层，再设计修复。
- **Reason**: Evidence 先于 Root Cause（PROCESS.md §7）；无归因的修改不可验证。
- **Consequence**: 后续 ER 问题一律先评估可观测性是否足够，再立项修复设计。

## D-12 — 一个行为问题必须独立立项

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 2026-08-26 P018 立项）
- **Context**: P16 问题同时含题记污染（P16-a）与正文 role sink（P16-b）；合并处理导致归因混乱（「顺顺→父亲」被误判为 P16-a 失败）。
- **Decision**: 一个行为问题一个独立 Problem Record（P16-b 独立为 P018）；独立归因、独立验证、独立结论，不合并为单一策略。
- **Reason**: 合并立项使「机制 A 成功 + 机制 B 失败」无法分别判断，产生错误归因。
- **Consequence**: 新问题先分类（层归属 + 行为独立），再决定是否单独立项（PROCESS.md §3）。

## D-13 — merge / resolver / extraction 职责边界

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.2.3-b1/b2）
- **Context**: canonical 合并曾与 resolver 状态耦合（改写 known 导致不一致）；抽取、消歧、合并三层职责混淆导致归因困难。
- **Decision**:
  - extraction 只负责 mention discovery 与 category 标注；
  - resolver 负责 mention→canonical 解析与 alias 注册（整本状态）；
  - merger 负责跨 chunk 聚合 + merge 决策（b1，纯内存，不改写 resolver 状态）+ 应用（b2，merge_map 交 db 单事务执行）；
  - merger **不得**对抽取结果做语义再解释。
- **Reason**: 决策与应用分离、层间契约清晰，保证可测试性与事务原子性。
- **Consequence**: 归因链固化（extraction coverage ≠ recall ≠ judge ≠ admission ≠ registration ≠ merge，见 `backend/app/pipeline/PIPELINE_LAYER.md` §4）；修改任一层的决策语义需先读对应 Layer 文档。

## D-14 — 进程内 JobStore，不引入 Redis

- **Status**: Accepted（含已知限制）
- **Date**: 2026-08-27（记录；形成于 V0.1）
- **Context**: 单进程部署足够；任务状态无需跨进程共享。
- **Decision**: `JobStore` 为进程内存储（threading.Lock 保证线程安全）；**已知限制：进程重启后任务丢失**，后续版本替换为持久化任务存储。
- **Reason**: 避免引入 Redis 的运维成本；V0.1 规模下单进程满足需求。
- **Consequence**: 重启后小说/任务消失属已知限制（P13 相关经验）；持久化替换是未来独立立项。

## D-15 — hygiene 只做 high-confidence hard filter

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.2.4）
- **Context**: mention 分类若由 hygiene 全部承担会与 LLM category 冲突，且确定性规则误伤风险高。
- **Decision**: `hygiene` 只返回 COLLECTIVE / INVALID（确定性硬规则）与 GENERIC 精确词表；**不得**返回 GENERIC/DESCRIPTIVE/COMPOSITE 分类（返回 None → resolver 用 LLM category 或 legacy PERSON fallback）。
- **Reason**: 分层决策——确定性规则只处理高置信情况，语义分类交给 LLM；避免规则与模型冲突。
- **Consequence**: category=None 的兜底路径是设计性 Known Limitation（D-10）；hygiene 的规则修改需跑 `test_hygiene.py` 全量回归。

## D-16 — section 分类为项目级启发式

- **Status**: Accepted
- **Date**: 2026-08-27（记录；形成于 V0.2.5-a）
- **Context**: 非正文（版权/题记/推广）污染 canonical 首现（P016）；需要确定性分类但标记词表依赖语料。
- **Decision**: `sections` 用标题关键词 + 首行标记启发式分类（METADATA/EPIGRAPH/BODY/TRAILER），默认 BODY 保守；标记词表是《边城》等中文 EPUB 验证的**项目级规则，不是通用语义规则**——换小说时需重新评估（与 D-7 同哲学）。
- **Reason**: 确定性优先（不引入 LLM 分类依赖）；默认 BODY 避免误伤正文。
- **Consequence**: 非正文 canonical 门控（provisional/promotion/flush）依赖该分类；换语料时复核词表。

## D-17 — P017 D5-b / B-1：LLM generic + judge null 不再进入 canonical fallback（V0.2.8）

- **Status**: Accepted（已实现并验证）
- **Date**: 2026-08-27（记录；实现于 V0.2.8，commit `a9a38f9`；D5-a A/B 报告 commit `cd52844`）
- **Context**: D5-b 缺口——LLM 标注 category=GENERIC 且 judge 返回 null 的 mention，经 legacy PERSON fallback 仍注册 canonical（母亲 generic + judge null → 独立 Person mc=7 实证）；null / missing / exception 三路径行为不一致。B-1 构建在 V0.2.5-b 的 B1 chunk 内 deferred 机制之上（B1 机制见 P017 §13 与 `docs/superpowers/specs/2026-08-26-v025b-descriptive-policy-design.md`）。
- **Decision**: `_is_effective_generic` 与 `_resolve_name` 对齐 + `_chunk_dropped` 防泄漏：LLM category=GENERIC + judge null 不再进入 canonical fallback；null / missing / exception 三路径统一为 dropped。未改 P16-b gate / generic 词表 / prompt（纯结构规则对齐，**非 classifier**，符合 D-10）。
- **Reason**: 消除「generic 标签在 judge-null 路径失效 → 碎片注册」；修复手段限制在结构规则，遵守 D-10 约束（不引入 classifier 绕过 D5）。
- **Consequence**: 真实《边城》重跑：16 个 LLM generic mention 由 null_registered 碎片改为 dropped；母亲 无独立 Person（judge 判 女孩子的母亲 → alias）。**D5-a（extraction coverage，prompt A/B）独立实验**：B prompt 未被采纳（保持 A=当前 prompt），覆盖增益有限且伴随 descriptive 化风险——coverage 缺失更可能属模型域（P06 提取方差），见 `docs/evaluation/2026-08-27-biancheng-d5a-prompt-ab.md`。

---

## D-18 — Checkpoint 是 durable recovery state，Job 是 execution handle

- **Status**: Accepted（已实现并真实评估验证）
- **Date**: 2026-08-28（P19 Resumable Analysis；实现 commit `d726d2f`；真实评估报告 `docs/evaluation/2026-08-28-biancheng-p19-resume-eval.md`）
- **Context**: 一次小说分析消耗大量 token；job 中途失败（token quota / 网络 / 进程异常）后已完成 chunk 无持久化恢复能力，重跑重复消耗全部 token（P19）。JobStore 为进程内存储（D-14 已知限制：重启丢失）。
- **Decision**:
  1. **分层**：`job_id` = 当前执行实例（进程内，不复活）；`novel_id` = 小说身份（可被新 job 复用）；**checkpoint = durable recovery state**（「Job 是 execution handle，Checkpoint 才是 recovery state」）；
  2. **双层持久化**：extraction 成功即持久化；judge 成功即持久化（失败不落盘 → 恢复时重试）；merge judge 同样重放；
  3. **身份与指纹**：EPUB sha256 为内容身份；`config_fingerprint`（schema/chunking/extractor/prompt×3/**model**/chunk_size/overlap）判定分析配置兼容（换模型 = 旧 checkpoint 作废，必须重跑）；`structure_hash` 为 chunking 产物 integrity check；judge identity = `chunk_id + judge_version + judge_input_fingerprint`（**不绑定 chunk_id alone**——候选集/resolver 状态变化时旧结果不得复用）；
  4. **同文件自动续跑**：`POST /api/novels` 不变；重传同 EPUB 且指纹兼容 → 复用 novel_id 续跑（跳过 COMPLETED、重试 FAILED）；完整完成重传 → 幂等（新 terminal job，零 LLM）；
  5. **manifest 两态**：`IN_PROGRESS / COMPLETED`；COMPLETED 准入 = 无 FAILED extraction + 无 judge 失败 + 无 merge 缺口 + 写库成功（job 终态与 manifest 状态解耦）；
  6. **CheckpointStore 层职责**：只做纯 I/O（原子写 / 路径防护 / 复合索引 `content_hash:config_fingerprint` / 损坏与写失败降级）；**不做任何业务决策（含兼容判定，归 api 层）**；
  7. **失败不熔断**：FAILED chunk 每次 resume 重新尝试（attempts 仅观测计数）。
- **Reason**: 恢复目标 = 已完成阶段零重复 LLM 调用；resolver 确定性 + 输入指纹重放保证恢复与全量运行一致；避免 Redis / 持久化 JobStore 的运维成本（D-14 哲学延续）。
- **Consequence**:
  - checkpoint 目录（`er_checkpoint_dir`，默认 `checkpoints/`）为 durable 中间态；Neo4j 仍是最终图唯一权威；
  - 换模型 / prompt / chunk 配置任一变化 → 旧 checkpoint 作废（全新分析）——实验性改动（如 prompt A/B）天然不能复用旧 checkpoint，符合归因纪律；
  - 新增 checkpoint 层（`backend/app/checkpoint/`，CHECKPOINT_LAYER.md），依赖方向 `api → checkpoint`（ARCHITECTURE.md 已更新）；
  - 删除小说须同时清理 checkpoint（`CheckpointStore.delete_novel`）；
  - 真实评估（qwen3.8-flash，中断 chunk20 → 重传续跑）：已完成 extraction 26/27 chunk 零重复、judge 19/19 全部重放（delta=0）、novel 复用 + 新 job、resume job completed（failed=[]）；AC-2 逐字节一致性在 mock 层成立（真实 LLM 下因 P06 方差不可逐字节比较）。

---

## 决策索引

| ID | Title | Status |
|---|---|---|
| D-1 | EPUB 作为输入格式 | Accepted |
| D-2 | novel_id + canonical identity 模型 | Accepted |
| D-3 | Person / RELATES_TO 数据模型边界 | Accepted |
| D-4 | canonical / alias 策略 | Accepted |
| D-5 | P16-b role admission evidence gate | Accepted |
| D-6 | P16-b verified / frozen | Frozen |
| D-7 | 不通过扩 generic 词表解决 P016/P018 | Accepted |
| D-8 | lineage 只允许旁路 observer | Accepted |
| D-9 | P017 D2：unresolved 不注册 | Accepted |
| D-10 | 不引入 classifier 绕过 P017 D5 | Accepted |
| D-11 | Task A 先于 Task B | Accepted |
| D-12 | 一个行为问题独立立项 | Accepted |
| D-13 | merge / resolver / extraction 职责边界 | Accepted |
| D-14 | 进程内 JobStore | Accepted |
| D-15 | hygiene 只做 hard filter | Accepted |
| D-16 | section 分类为项目级启发式 | Accepted |
| D-17 | P017 D5-b / B-1：generic + judge null 不进 canonical fallback（V0.2.8） | Accepted |
| D-18 | Checkpoint 是 durable recovery state，Job 是 execution handle（P19） | Accepted |
