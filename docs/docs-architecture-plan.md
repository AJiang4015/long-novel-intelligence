# 文档架构整理方案（第一阶段：设计 + 迁移清单）

> 状态：**待评审**（2026-08-27 快照）
>
> 范围：仅文档架构设计与迁移清单。**不修改**业务代码 / 测试 / prompt / schema / resolver / pipeline behavior；不重写既有 Problem / Spec / Evaluation；不顺手修历史问题。
>
> 本文是第一阶段交付物，评审通过后按 §6 迁移顺序执行；执行完成后本文可归档（或按评审意见保留为文档体系说明）。

---

## 0. 现状盘点（事实基线）

### 0.1 现有文档清单

| 文档 | 规模 | 现状职责 |
|---|---|---|
| `AGENTS.md` | 408 行 / 15 节 | 项目百科：规则 + 流程 + 架构 + 决策 + 问题历史 + 测试要求混装 |
| `PROBLEM.md` | 188 行 | 问题地图 + 诊断路由（§0 Do/Don't / §1 Routing / §2 Index / §3 Active / §4 Resolved / §5 目录） |
| `TESTING.md` | 176 行 | 测试与真实评估规范（§0-§9，已有完整骨架） |
| `DESIGN.md` | — | UI/UX Design System 唯一事实来源 |
| `README.md` | 47 行 | 快速上手 + API 表 + V0.1 已知限制（**部分已过时**，见 §3.4） |
| `docs/problems/` | 11 份 | P001 / P004-P011 / P016 / P017 / P018 完整 Problem Record |
| `docs/superpowers/specs/` | 14 份 | 各版本设计文档（Design Spec） |
| `docs/superpowers/plans/` | 9 份 | 实施计划 |
| `docs/evaluation/` | 5 份 | 真实 LLM 评估报告 |

### 0.2 后端分层事实（Layer 文档的事实来源）

| 层 | 模块 | 已确认职责 |
|---|---|---|
| `api/` | novels / characters / jobs / health | HTTP 边界、DTO 转换、ingest 编排（`_run_ingest`：epub→chunk→extract→resolve→merge→write→job）、job 状态暴露 |
| `db/` | neo4j.py (`Neo4jDB`) | 按 novel_id 隔离的读写、约束管理（`(novel_id,name)` UNIQUE）、`delete_novel` 精确删除、`upsert_graph` 单事务 |
| `models/` | job.py (`JobStore`/`JobState`/`JobStatus`) | 进程内任务状态机（已知限制：重启丢失，未来换持久化） |
| `pipeline/` | epub_reader / sections / chunker / llm_client / extractor / hygiene / resolver / merger / lineage | 见 §4.5 PIPELINE_LAYER 决策所有权矩阵 |
| `schemas/` | api.py（DTO）、llm.py（`MentionCategory`/`ExtractionResult`/`AliasJudgeResult` 等） | 跨层数据契约；`schemas/api.py` 复用 `models.job` 类型 |

依赖方向（代码事实）：`api → {pipeline, db, models, schemas, config}`；`pipeline → schemas`；`schemas/api.py → models`；`main.py` 组装全局依赖。

### 0.3 核心诊断：AGENTS.md 的问题

1. **混合承载**：规则 / 流程 / 架构 / 决策 / 问题历史 / 测试要求 6 类内容共存 408 行，Agent 无法快速区分「必须遵守」与「背景知识」。
2. **与既有文档重复**：§8↔TESTING §1/2/7、§9↔TESTING §3/6/9、§15↔PROBLEM §0，且**同一规则多处表述已漂移**（见 §3）。
3. **决策未沉淀**：P16-b gate / generic 词表 / lineage 旁路 / P17 D2 等已落地决策散落在代码注释、Problem Record、Spec 中，没有统一的 Decision Record。
4. **层归属无文档**：extraction coverage / recall / judge / admission / registration / merge 六类失败的归因规则只存在于 Problem 记录，没有固化到层契约。

---

## 1. AGENTS.md 408 行分类结果（交付物 1）

分类定义：**A**=Mandatory Agent Rule ｜ **B**=Process/Workflow ｜ **C**=Architecture ｜ **D**=Long-term Decision ｜ **E**=Problem-specific history ｜ **F**=Testing/Evaluation ｜ **G**=Temporary/Obsolete

| AGENTS.md 节（行号） | 内容 | 分类 | 去向 | 原位置保留？ | 备注 |
|---|---|---|---|---|---|
| §1 Project Overview（L3-18） | 项目目的 + 技术栈 | C | ARCHITECTURE.md §0 | ❌ | AGENTS 仅留 1 行身份指针；stack 细节入 ARCHITECTURE |
| §2 Source of Truth（L22-77） | 文档管辖地图（DESIGN/TESTING/PROBLEM） | A+D | AGENTS.md §0 文档地图（重写精简） | ✅（改写） | 变为「谁管什么」地图，每文档 1-2 行；扩展进 PROCESS/DECISIONS/ARCHITECTURE/*_LAYER |
| §3 Before Starting a Task（L81-98） | 开工必读顺序 + 工作区检查 | A | AGENTS.md §1 | ✅ | 跨任务硬约束，原样保留 |
| §4 Scope Control（L102-115） | 最小修改原则 | A | AGENTS.md §2 | ✅ | 硬约束，原样保留 |
| §5 Bug Investigation（L119-144） | diagnose/fix 模式 | A+B | AGENTS.md（只读约束）+ PROCESS.md §1 + 引用 bug-investigation skill | 部分 | 「diagnose 只读 / 修复须授权」=A 保留；「复现→证据→根因→方案→验证」=B 入 PROCESS |
| §6 Code Changes（L148-160） | 修改代码流程 | A+B | AGENTS.md（兼容性铁律）+ PROCESS.md §5 | 部分 | 步骤 1-7 = B 入 PROCESS；「API/DTO 向后兼容」「不为漂亮改稳定行为」=A 保留 |
| §7 Neo4j Safety Rules（L164-194） | 数据模型边界 + 删除纪律 | A+D | AGENTS.md §2（禁止项）+ DECISIONS.md D-3/D-2（边界与隔离决策） | ✅（规则部分） | 禁令保留；「为什么独立实例/只三种标签」入 DECISIONS |
| §8 Test Data Isolation（L198-216） | 测试数据隔离 | A+F | AGENTS.md §3（铁律 1-2 行）+ TESTING.md（细节已在 §1/2/7） | ✅（精简） | 与 TESTING.md 去重；eval 用新 novel_id 已在 TESTING §3 |
| §9 Real LLM Evaluation（L220-255） | 评估规范 + V0.2.5 指标 + 归因纪律 | A+F+E | TESTING.md（A/F）+ docs/problems/P018/P017/P006（E） | ❌（精简为指针） | 细节 TESTING §3/6/9 已覆盖；归因纪律归各 Problem Record |
| §10 Problem Knowledge Base（L259-306） | PROBLEM.md 维护规范 + 10 条 Rule | D+A | PROBLEM.md（维护规范移入自身）+ AGENTS.md §1（3-4 条硬规则） | ❌（精简） | 打破循环引用（PROBLEM 现反指 AGENTS §10） |
| §11 Documentation Consistency（L310-319） | 文档职责分流 | A | AGENTS.md §0 文档地图（并入） | ✅（并入） | 本方案即其扩展 |
| §12 Git（L323-343） | git 纪律 | A+B | AGENTS.md §4（禁止项）+ PROCESS.md §4（status/diff/独立 commit） | 部分 | 「reset --hard / 删他人修改 / force push」=A；「独立 commit」=B 固化 |
| §13 Final Verification（L347-363） | 收尾验证 + 报告格式 | A+B | AGENTS.md §5（必测 checklist）+ PROCESS.md §4（报告模板） | 部分 | 必测清单=A；报告 6 项=B |
| §14 Default Principle（L367-375） | 核心原则五句 | A | AGENTS.md §6 | ✅ | 宪法序言保留 |
| §15 Do/Don't（L379-408） | 高频踩坑速查 | A+D+E+F | 拆分（见 §1.1） | ❌（拆分） | 与 PROBLEM.md §0 去重；决策/归因类条目另有归属 |

### 1.1 §15 Do/Don't 逐条拆分

**Do 项**

| 条目 | 分类 | 去向 |
|---|---|---|
| 删除数据一律 `db.delete_novel(novel_id)`（dry-run 列目标） | A | AGENTS.md §2 |
| 每个测试用例独立 `novel_id`，只清理自己的 | A | AGENTS.md §3 |
| `EntityResolver` 一次 ingest 一个实例 | D | DECISIONS.md D-4（resolver 状态语义） |
| 长任务脚本 `python -u` + 后台任务 | A | AGENTS.md §3（运行纪律，简短保留） |
| 真实评估前记录 Environment Baseline | F | TESTING.md §6（已存在） |
| 修改 resolver.py 后跑回归（test_resolver*/hygiene/sections） | F | TESTING.md §8（以 TESTING.md 为准统一，见 §3.2） |
| 修改 ER 相关代码后跑全量 unit+integration（含基线计数） | F | TESTING.md §8（**版本基线计数属 G**，入版本化小节） |
| LLM 报错先看 `[llm] stage/status/code` 日志 | A | AGENTS.md §3 + PROBLEM.md §1（已存在） |
| 改 `.env` 后重启后端 | A | AGENTS.md §3（简短保留） |
| 真实评估报告附 V0.2.5 验收指标 | F | TESTING.md §9 + 对应版本 evaluation 文档 |

**Don't 项**

| 条目 | 分类 | 去向 |
|---|---|---|
| 全库 DELETE / DETACH DELETE（含 `MATCH (n:Novel) DELETE n`） | A | AGENTS.md §2（唯一权威位置） |
| 跨 novel_id 查询或清理 Person | A | AGENTS.md §2 |
| 不在 diagnose 模式修改代码/数据/配置 | A | AGENTS.md §2 |
| 不依赖「数据库初始为空」 | A | AGENTS.md §3 |
| 不把一次真实 LLM 评估当 deterministic 测试 | A | AGENTS.md §3 |
| 不为「代码更漂亮」改稳定 API/DTO/行为 | A | AGENTS.md §2 |
| 不把 LLM 非确定性写死进测试 | A | AGENTS.md §3 |
| **不把「父亲/母亲/祖父」加入 generic 词表** | D+E | DECISIONS.md D-7 + P016/P018 Record |
| **不因「顺顺→父亲」判 P16-a/P17 失败** | E | P018 Record（归因纪律） |
| **不引入 classifier 绕过 P017 D5** | D+E | DECISIONS.md D-10 + P017 Record |
| **不把「DESCRIPTIVE/COMPOSITE 无法确认→不注册」当回归** | D | DECISIONS.md D-9 + P017 Record |

---

## 2. 各目标文档职责与内容设计（交付物 2/3/4/5/6）

### 2.1 AGENTS.md ——「Agent 宪法」（交付物 6：必须留在原位的）

目标结构（预计 100-150 行，全部为跨任务硬约束，不承载背景推导）：

```text
# AGENTS.md
## 0. 项目身份（1 行）+ 文档地图
     AGENTS=必须遵守什么 / PROCESS=应该怎么工作 / DECISIONS=决定了什么、为什么 /
     ARCHITECTURE=系统怎么组织 / *_LAYER=每层负责什么、不能负责什么 /
     PROBLEM=哪里有问题 / SPEC=准备怎么改 / EVALUATION=改完实际怎么样 /
     TESTING / DESIGN 各自管辖范围（从 §2 精简而来）
## 1. 开工前必读（原 §3）+ 问题知识库硬规则 4 条（原 §10 精简）
## 2. 硬性禁止与边界
     - 无范围 destructive query / 跨 novel_id 操作（原 §7/§15）
     - diagnose 模式只读（原 §5 A 部分）
     - 跨层越界（指向 ARCHITECTURE.md 与 *_LAYER.md 的边界规则）
     - 稳定 API/DTO/行为不改（原 §6/§4）
     - generic 词表红线 / classifier 绕过红线（指向 DECISIONS.md）
## 3. 测试与评估铁律（原 §8/§9 精简为规则 + 指针）
     - 测试隔离 / eval 用新 novel_id / eval 非 deterministic / [llm] 日志
## 4. Git 约束（原 §12 A 部分）
## 5. 收尾必做 checklist（原 §13 A 部分）
## 6. 默认原则（原 §14）
```

**必须留在 AGENTS.md 的判定标准**：满足「长期有效、跨任务适用、违反即导致项目不正确/数据损坏」三条中任意一条。其余一律迁出。

### 2.2 PROCESS.md ——「应该怎么工作」（交付物 2）

定位：任务怎么做，不解释为什么这么设计。内容：

```text
# PROCESS.md
## 0. 流程总览
Problem → Evidence → Problem classification / layer attribution → Spec → Review
→ Implementation → Unit → Integration → Real LLM evaluation → Evaluation report
→ Decision → Commit
## 1. 问题处理流程（原 AGENTS §5 B 部分 + §10 操作要求）
     - 症状 → §1 Diagnostic Routing（PROBLEM.md）→ 读对应 Problem Record
     - Evidence 先于 Root Cause；区分 症状/直接原因/根因
     - 归因到「拥有该决策的层」（见 §1.1 归因链），不是哪里方便改哪里
## 2. 真实 LLM 实验规范（原 AGENTS §9 F 部分，与 TESTING.md 分工：PROCESS 讲流程，
    TESTING 讲参数/模板）
     - 变量固定原则：一次实验只允许一个变量变化
     - fresh novel / fresh job 要求
     - A/B 实验唯一变量保证（除被测变量外 Environment Baseline 全等）
     - 验收顺序：unit → integration → real ingest（不得跳级下结论）
     - lineage 使用方式：ER_LINEAGE=1 + tools/diagnose_lineage.py 离线归层（指向
       docs/superpowers/specs/2026-08-27-p06-lineage-observability-design.md）
## 3. 问题立项与提交纪律
     - 一个行为问题一个独立立项（P16-b 独立为 P018 的模式）
     - 一个问题一个独立 commit
## 4. 修改与验收流程（原 AGENTS §6 B + §12 B + §13 B）
     - 修改前：git status / git diff；先说明范围
     - 修改后：相关测试 → build/type check → git diff → 范围确认 → 报告 6 项
## 5. 核心组件修改准入（何时允许改 prompt/resolver/schema/merger）
     - 前置条件：有 Problem Record（Evidence）→ 有 Spec → 有 Review
     - 未经归因的修改禁止；临时结论不得直接进入实现
## 6. 失败归因与止损
     - 多轮尝试无新证据时回到 Evidence，不继续无依据修改
     - 已 resolved 问题复发：先查 code regression / env / model / input change
       （Do Not Reopen 检查），不盲目重复旧修复
## 7. 固化优先级原则
     Task A 先于 Task B ｜ Problem 先于 Code ｜ Evidence 先于 Root Cause ｜
     Real evaluation 先于结论
```

### 2.3 DECISIONS.md ——「已经决定了什么、为什么」（交付物 3）

Decision Record，不是问题记录也不是实现说明。模板与候选条目：

```text
Decision ID ｜ Title ｜ Status（Accepted/Superseded/Frozen）｜ Date ｜ Context ｜
Decision ｜ Reason ｜ Consequence
```

| ID | Title（候选） | Status | 证据来源（迁移时补 Date/Commit） |
|---|---|---|---|
| D-1 | EPUB 作为输入格式 | Accepted | README / epub_reader 链路 |
| D-2 | novel_id + canonical identity 模型（`(novel_id,name)` UNIQUE） | Accepted | `db/neo4j.py` ensure_constraints；resolver known/canonical_aliases |
| D-3 | Person / RELATES_TO 数据模型边界（只 Novel/Person/RELATES_TO，独立实例） | Accepted | AGENTS §7 + P02（共享实例事故） |
| D-4 | canonical / alias 策略：首现定主名、aliases 保序去重不含 canonical、mention_count=distinct chunk | Accepted | TESTING §8；resolver 实现 |
| D-5 | P16-b role admission evidence gate（bare 证据门槛 / qualified 对齐 + anchor 在场） | Accepted | P018 Record + p16b spec |
| D-6 | P16-b verified / frozen（mechanism PASS / capability PARTIAL，冻结不修） | Frozen | P018 Record + v026 eval |
| D-7 | 不通过扩 generic 词表解决 P016/P018（RC3 已锁；换小说需重新评估） | Accepted | hygiene.py 注释 + P016/P018 Do Not Reopen |
| D-8 | lineage 只允许旁路 observer（ER_LINEAGE 默认关零开销；不参与判定） | Accepted | lineage.py docstring + Task A spec |
| D-9 | P017 D2：DESCRIPTIVE/COMPOSITE 无法确认 → unresolved 不注册 | Accepted | P017 Record + v025b spec + test_hygiene.py:176 |
| D-10 | 不引入 classifier 绕过 P017 D5（Known Limitation，走 P06 follow-up） | Accepted | P017 Record + p017-d5 spec |
| D-11 | Task A 先于 Task B（归层先于修复设计） | Accepted | P06 Task A/B 序列 |
| D-12 | 一个行为问题必须独立立项（P16-b 从 P16 拆出 P018） | Accepted | PROBLEM §3 P18 |
| D-13 | merge / resolver / extraction 职责边界（b1 decision → b2 apply 纯内存；merger 不重释抽取） | Accepted | resolver/merger 实现 + merge specs |
| D-14 | 进程内 JobStore，不引入 Redis（已知限制：重启丢失） | Accepted | models/job.py 注释 + README |
| D-15 | hygiene 只做 high-confidence hard filter，不返回 GENERIC/DESCRIPTIVE/COMPOSITE | Accepted | hygiene.py docstring |
| D-16 | section 分类为项目级启发式（换小说需重新评估） | Accepted | sections.py docstring |

> 迁移执行时：D-5/D-6/D-9/D-10 等条目需从对应 Problem Record 的 Decision 字段提取 Date / Related Commits / Trade-offs 补齐；**不把单次实验结论升级为 Accepted**（如 merge INCONCLUSIVE 只记入 evaluation，不升 Decision）。

### 2.4 ARCHITECTURE.md ——「系统怎么组织」（交付物 4）

全局架构地图，不写逐文件说明：

```text
# ARCHITECTURE.md
## 0. 项目概述与栈（原 AGENTS §1 迁入）
## 1. 数据流
EPUB
 ↓
API / ingestion orchestration（api/novels._run_ingest，后台 job）
 ↓
epub_reader（EPUB → chapters）→ sections（section 分类）→ chunker（切块）
 ↓
extractor（并发 LLM 抽取；concurrency 来自配置）
 ↓
hygiene（deterministic hard filter）→ resolver（recall → judge → admission → registration；
   role gate / provisional / deferred / unresolved）
 ↓
merger（跨 chunk 聚合 → merge decision(b1) → merge apply(b2)）
 ↓
db / Neo4j（单事务 upsert_graph；按 novel_id 隔离）
 ↓
API response（characters 查询 / 关系图）
## 2. 层与模块职责表（每层 1-3 行；细节指向对应 *_LAYER.md）
## 3. 依赖方向（代码事实）
   api → {pipeline, db, models, schemas, config} ｜ pipeline → schemas ｜
   schemas/api.py → models ｜ main 组装全局依赖
## 4. 边界规则（禁止跨层实现清单）
   - api 层不实现 ER/合并/分类逻辑
   - pipeline 不直接访问 Neo4j / 不接触 HTTP
   - db 层不做业务决策
   - models 不依赖 pipeline/LLM/db
   - lineage 不得参与任何判定
## 5. 数据进出：在哪里进入（EPUB）、在哪里转换（pipeline）、在哪里持久化（Neo4j）
## 6. 与 Layer 文档的关系
```

### 2.5 五个 Layer 文档（交付物 5）——统一 11 点契约模板

五个文档统一模板（`*_LAYER.md` = Layer Contract / Boundary，**不是**代码使用说明）：

```text
1. Responsibility          这一层负责什么
2. Input contract          进入本层的输入契约
3. Output contract         本层产出的输出契约
4. Decision ownership      本层拥有哪些决策权
5. Allowed dependencies    允许依赖哪些层/模块
6. Forbidden dependencies  禁止依赖哪些层/模块
7. Invariants              本层必须维持的不变量
8. Failure ownership       本层的失败由谁负责、如何暴露
9. Testing expectations    本层测试预期
10. Typical changes allowed here        允许在本层做的典型修改
11. Changes that must be implemented elsewhere  必须放到别处的修改
```

#### 2.5.1 PIPELINE_LAYER.md（最重要，含决策所有权矩阵）

```text
## 决策所有权矩阵
Extractor（extractor.py + llm_client.py + epub_reader.py + sections.py + chunker.py）
  owns:    输入适配（EPUB/章节/切块/section 分类）
           mention discovery（是否被抽取、抽取覆盖）
           extraction category（LLM 标注 category；category=None 为契约允许值）
           并发抽取编排、重试/错误区分（retryable vs validation）
  does NOT own:
           canonical resolution
           alias admission
           merge decision

Hygiene（hygiene.py）
  owns:    deterministic hard rules：COLLECTIVE / INVALID 过滤
           relational generic 精确词表（RC3）
  does NOT own:
           返回 GENERIC / DESCRIPTIVE / COMPOSITE 分类（返回 None，交 LLM category）

Resolver（resolver.py）
  owns:    mention → canonical resolution（recall → judge → admission → registration）
           role admission（P16-b evidence gate / qualified 对齐）
           alias registration（canonical_aliases / known 整本持续）
           effective category usage（LLM category → hygiene 兜底 → legacy PERSON fallback）
           provisional / promotion / flush（非正文注册门控）
           deferred / unresolved 决策（P17 D2）
  does NOT own:
           merge decision / merge apply（decide_merges 产物仅交 merger/db 执行）

Merger（merger.py）
  owns:    cross-chunk aggregation（PersonAgg / RelAgg / weight / confidence）
           merge decision（b1：decide_merges 纯内存决策）
           merge application（b2：merge_map 交给 db 单事务执行）
  does NOT own:
           semantic re-interpretation of extraction（不改写抽取语义）

Lineage（lineage.py）
  owns:    observation only（事件记录 / lineage_id join / 终态 flush）
  MUST NOT:
           participate in business decisions
           modify resolver / extraction output
           alter merge behavior
           （默认关闭 ER_LINEAGE=0，no-op 零开销）

## 归因链（固化：先归到拥有该决策的层，不是哪里方便改哪里）
extraction coverage failure（抽取覆盖缺失）   → extractor 层    → P017 D5-a
≠ recall failure（候选召回）                 → resolver recall → P08
≠ judge failure（判定非确定性/误判）          → resolver judge  → P06
≠ admission failure（准入拦截误判）           → resolver role  → P16-b / P18
≠ registration failure（注册/alias 策略）     → resolver 注册   → P17 D2
≠ merge failure（跨 chunk 合并）              → merger         → merge INCONCLUSIVE
```

其余 10 点（Input/Output/Invariants 等）在迁移执行时按各模块 docstring 与测试文件填充，要点：
- Input：`Chunk + ExtractionResult`（resolver）；`list[(Chunk, ExtractionResult)]`（merger）；`chapters`（chunker）；`EPUB bytes`（epub_reader）
- Invariants：resolver 一次 ingest 一个实例；merger 输入先按 chunk_id 排序；lineage 零 IO 默认关
- Testing：`tests/unit/test_{resolver,resolver_context,resolver_descriptive,role_policy,hygiene,merge,merger,lineage,chunker,sections,llm_client}.py` + TESTING.md §8 回归清单

#### 2.5.2 API_LAYER.md（api/）

- **Responsibility**：HTTP 边界、DTO 转换、ingest 编排（`_run_ingest` 流水线顺序）、job 状态暴露、健康检查
- **Input**：multipart `.epub`（≤50MB）、路径/查询参数
- **Output**：JSON DTO（`schemas/api.py`）+ 副作用（写库、job 更新）
- **Decision ownership**：端点契约、状态码、参数校验、ingest 编排顺序、job 终态映射
- **Allowed**：config / db / models / pipeline / schemas
- **Forbidden**：ER 判定、cypher、LLM prompt、合并决策
- **Invariants**：DTO 向后兼容；Neo4j 不可用 → 503；上传校验先行
- **Failure ownership**：端点级 HTTPException；LLM/解析失败 → job failed_blocks + 状态（P11）
- **Testing**：integration（`test_api_neo4j.py`）；异常路径单测
- **Allowed changes**：新增端点、参数、编排顺序调整
- **Elsewhere**：所有业务决策（见 PIPELINE_LAYER）

#### 2.5.3 DB_LAYER.md（db/）

- **Responsibility**：Neo4j 访问封装、按 novel_id 隔离的读写、约束、单事务写入
- **Input**：novel_id + 领域对象（`MergedGraph`、`merge_map`、chapters）
- **Output**：持久化状态 / 查询结果
- **Decision ownership**：写库事务边界、约束定义、删除语义（`delete_novel` 按 id）
- **Allowed**：neo4j driver（唯一）
- **Forbidden**：业务决策（合并判断/canonical 选择/role 判定）；无范围 DELETE；其他标签
- **Invariants**：属性仅原始类型（chapters JSON 序列化）；事务回滚无半态；`(novel_id,name)` 唯一
- **Failure ownership**：连接错误、ResultConsumedError、事务回滚（P14）
- **Testing**：integration + 独立 novel_id 自建自清
- **Allowed changes**：查询封装、约束、事务写法
- **Elsewhere**：canonical merge 判定、mention 分类、prompt

#### 2.5.4 MODEL_LAYER.md（models/）

- **Responsibility**：进程内领域状态（JobStore / JobState / JobStatus / FailedBlock）——任务生命周期状态机
- **Decision ownership**：job 状态机合法转换（pending→running→completed/completed_with_errors/failed）；P11「全失败→failed」规则归属此处
- **Allowed**：pydantic + threading（无外部依赖）
- **Forbidden**：不 import pipeline/LLM/db；不持久化
- **Invariants**：进程内（重启丢失 = 已知限制，未来持久化替换）；Lock 保证线程安全
- **Failure ownership**：状态机非法转换、并发读写
- **Testing**：unit（`test_job_store.py`）
- **Allowed changes**：状态字段、状态机规则、未来持久化替换
- **Elsewhere**：业务结果判定

#### 2.5.5 SCHEMA_LAYER.md（schemas/）

- **Responsibility**：跨层数据契约：`llm.py`（MentionCategory / Character / Relationship / ExtractionResult / AliasCandidate / PendingMention / AliasJudgeResult）+ `api.py`（DTO）
- **Decision ownership**：字段约束（name≤50、confidence∈[0,1]）、枚举语义（MentionCategory 是 extract 契约）、模型校验（self-loop 丢弃）
- **Allowed**：pydantic；`api.py` 可依赖 `models`（复用 JobState/JobStatus）；`llm.py` 独立
- **Forbidden**：不依赖 pipeline/db；不承载业务逻辑
- **Invariants**：契约稳定（修改需向后兼容）；枚举值稳定
- **Testing**：模型校验单测
- **Allowed changes**：新增 DTO/字段（兼容）、新枚举（需评审）
- **Elsewhere**：决策逻辑（见 PIPELINE_LAYER）

---

## 3. 重复 / 冲突 / 过时规则清单（交付物 7）

### 3.1 重复（同一规则多处承载）

| 规则 | 出现位置 | 处理 |
|---|---|---|
| 全库 DELETE 禁令 | AGENTS §7、§8、§15 ｜ TESTING §1 ｜ PROBLEM §0 ｜ P001 | 权威位置 = AGENTS §2；其余改指针 |
| 测试独立 novel_id / 自清 | AGENTS §8 ｜ TESTING §1/2/7 ｜ PROBLEM §0 | 权威 = TESTING §1；AGENTS 留铁律 |
| 真实评估记录字段 / fresh novel | AGENTS §9 ｜ TESTING §3/6 ｜ PROBLEM §0 | 权威 = TESTING §3/6 |
| eval 非 deterministic | AGENTS §9、§15 ｜ TESTING §3 ｜ PROBLEM §0 | 权威 = AGENTS §3 铁律 |
| 归因纪律（顺顺→父亲 / ch5b / merge failed） | AGENTS §9、§15 ｜ PROBLEM §0、§3 ｜ P017/P018 | 权威 = 各 Problem Record；AGENTS 不留 |
| Do/Don't 表 | AGENTS §15 ｜ PROBLEM §0 | **两表已漂移**（见 3.2），以 PROBLEM §0 + DECISIONS 为准统一 |

### 3.2 冲突（同规则表述不一致）

| 规则 | 冲突点 |
|---|---|
| resolver 修改后回归命令 | AGENTS §15：「test_resolver*.py / test_hygiene.py / test_sections.py 全量回归（含 V0.2.5 T-a/T-b 矩阵）」vs PROBLEM §0：「test_resolver.py 回归清单（TESTING.md §8）」vs TESTING §8 具体命令——**三处不一致**，统一以 TESTING.md §8 为准 |
| 基线计数 | AGENTS §15「unit 188 / integration 15」为 V0.2.5 快照，会漂移 → 移入 TESTING.md 版本化小节 |
| generic 词表红线 | AGENTS §15 说「父亲/母亲/祖父」；PROBLEM §0 说「父亲/母亲/祖父」；hygiene.py 注释确认祖父/父亲/母亲**不在** `_RELATIONAL_GENERIC_WORDS`——迁移时以代码事实为准复核 |

### 3.3 循环引用

- PROBLEM.md L6：「维护规则与记录标准见 AGENTS.md §10」——PROBLEM 的维护规范反指 AGENTS。迁移后规范移入 PROBLEM.md 自身，AGENTS 只留引用。

### 3.4 过时（G 类）

| 位置 | 内容 | 处理 |
|---|---|---|
| README.md「V0.1 已知限制」 | 「人物不做别名归并：不同写法视为不同 Person」——**V0.2.x 已实现 alias 归并**，与现状矛盾 | 迁移执行阶段修订 README（本轮不动） |
| README.md「V0.1 验收记录」 | 全部 checkbox 为 V0.1 遗留 | 执行阶段清理/归档 |
| AGENTS §15 | 「unit 188 / integration 15」「V0.2.5 T-a/T-b 矩阵」版本化计数 | 移入 TESTING.md 版本化小节（标注版本） |
| AGENTS §9 | 「V0.2.5 起强制」评估报告声明 | 声明本身为长期规则（入 TESTING §9）；「V0.2.5 起」措辞去掉版本前缀 |

---

## 4. 最终推荐文档树（交付物 8）

```text
根目录
├── AGENTS.md           宪法：硬规则（~120 行）＋文档地图
├── PROCESS.md          流程：应该怎么工作（新建）
├── DECISIONS.md        决策记录：决定了什么、为什么（新建）
├── ARCHITECTURE.md     系统结构：数据流/依赖/边界（新建）
├── PROBLEM.md          问题地图 + 诊断路由（结构不变；§0 去重、维护规范移入）
├── TESTING.md          测试规范（结构不变；吸收 AGENTS §9 细节 + 版本化指标）
├── DESIGN.md           UI 规范（不动）
└── README.md           快速上手（执行阶段修订过时信息）

backend/app/
├── api/API_LAYER.md        Layer Contract（新建）
├── db/DB_LAYER.md          Layer Contract（新建）
├── models/MODEL_LAYER.md   Layer Contract（新建）
├── pipeline/PIPELINE_LAYER.md  Layer Contract + 决策所有权矩阵（新建，优先）
└── schemas/SCHEMA_LAYER.md Layer Contract（新建）

docs/
├── problems/           维持不动
├── superpowers/specs/  维持不动
├── superpowers/plans/  维持不动
└── evaluation/         维持不动
```

**保持边界长期稳定的规则**（写入 AGENTS §0 文档地图）：新增文档先判断属于哪一类（规则/流程/决策/架构/层契约/问题/Spec/Evaluation），禁止继续向 AGENTS.md 追加。

---

## 5. 无规则丢失校验方法（交付物 10）

1. **迁移追踪表**：本文 §1 表格即追踪清单，执行时逐行核对：每个 AGENTS 段落 → 目标文件 §锚点，迁移后打勾（执行阶段生成核对版）。
2. **关键词 grep 校验**（迁移完成后必须通过）：
   - 禁令存在性：`DELETE n` / `DETACH DELETE` / `reset --hard` / `force push` / `generic` / `classifier` / `diagnose` → 必须仍出现在 AGENTS.md 或对应文档
   - 指针完整性：AGENTS.md 中引用的每个文档路径真实存在
3. **新旧对照 diff 审阅**：新文档必须「覆盖」旧内容，不允许「丢弃」；git diff 逐段对照。
4. **git 历史保留**：不 squash；迁移分阶段提交（见 §6），任一步可回滚。
5. **过渡注记**：迁移期间 AGENTS.md 顶部保留「本文件正在重构，规则以 PROCESS/DECISIONS/ARCHITECTURE/*_LAYER 为准」注记，迁移完成后删除。
6. **终态自检**：AGENTS.md 不再出现 Problem 编号详情（P0xx 只允许作为指向 docs/problems 的引用）；所有 D 类内容可在 DECISIONS.md 找到；所有 B 类内容可在 PROCESS.md 找到。

---

## 6. 建议迁移顺序（交付物 9，评审通过后执行）

| 阶段 | 动作 | 产出 | 验收 |
|---|---|---|---|
| P0 准备 | 确认 `git status` 基线；快照 AGENTS.md（本文 §1 已记录 2026-08-27 版） | 干净基线 | 无未提交改动 |
| P1 | 新建 `ARCHITECTURE.md`（AGENTS §1 + 代码事实） | ARCHITECTURE.md | 数据流/依赖/边界齐全 |
| P2 | 新建 `DECISIONS.md`（AGENTS D 类 + Problem Record Decision 字段 + 代码注释） | DECISIONS.md（D-1..D-16） | 每条含 Context/Reason/Consequence |
| P3 | 新建 `PROCESS.md`（AGENTS B 类 + 固化原则） | PROCESS.md | 流程闭环 §0-§7 |
| P4 | 新建 5 个 `*_LAYER.md`（**PIPELINE 优先**，含决策所有权矩阵） | 5 份 Layer 文档 | 11 点模板齐全 |
| P5 | 精简 `AGENTS.md`（保留 A 类，删 B/C/D/E/F 重复，加文档地图 + 指针） | 精简版 AGENTS.md（~120 行） | §5 校验项通过 |
| P6 | 同步：PROBLEM.md（§0 去重指向、维护规范移入、§1 路由补 layer 归属）；TESTING.md（吸收 §9、版本化指标）；README.md（修过时） | 三份文档更新 | 交叉链接完整 |
| P7 | 终态校验 + 审阅 | 一个迁移 commit（或按阶段多个 commit） | §5 全项通过 |

> 依赖关系：P1-P4 互不依赖可并行；P5 必须在 P1-P4 之后（AGENTS 精简后才有所指）；P6 在 P5 之后。

---

## 7. 本方案遵守的禁止项核对

- ✅ 不机械生成五个 README（改为 `*_LAYER.md` 契约文档）
- ✅ 不复制重复内容（§3 重复项以「单一权威 + 指针」处理）
- ✅ 不重写既有 Problem / Spec / Evaluation（docs/ 三目录维持不动）
- ✅ 不修改代码 / 测试 / prompt / schema / resolver / pipeline behavior（本轮零代码改动）
- ✅ 不因整理文档顺手修历史问题（README 过时项仅在 P6 修订，不涉及业务）
- ✅ 不把临时实验结论升级为永久 Decision（merge INCONCLUSIVE 等只入 evaluation，D 表仅收录已明确形成的决策）
