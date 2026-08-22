# PROBLEM.md — 项目问题地图 + Agent 诊断入口

> 本文件是**问题索引 + 诊断路由**，不承载长篇事故过程。
> 完整 forensic / postmortem / engineering record 在 `docs/problems/Pxxx-*.md`。
> 真实数据实验记录在 `docs/evaluation/`（Problem Record 只引用，不内嵌）。
> 维护规则与记录标准见 `AGENTS.md` §10（含 Problem Knowledge Rule）。

---

## 0. Critical Do / Don't（高频踩坑速查）

### Do

- 删除数据一律 `db.delete_novel(novel_id)`（按 id 精确；删除前 dry-run 列目标）
- 每个测试用例创建独立 `novel_id`，结束后只清理自己的
- `EntityResolver` 一次 ingest 一个实例（`known`/mention index 整本持续）
- 长任务脚本用 `python -u`（无缓冲）+ 后台任务方式运行
- 真实评估前记录 Environment Baseline（commit/model/chunk/concurrency/novel_id/Neo4j 版本）
- 修改 `resolver.py` 后跑 `test_resolver.py` 回归清单（TESTING.md §8）
- LLM 报错先看诊断日志 `[llm] stage=... status=... code=...`（区分 Arrearage/限流/validation）
- 改 `.env` 后必须重启后端（settings 进程内缓存）
- **遇到症状先走 §1 Diagnostic Routing，再读对应 Problem Record，不要凭经验改代码**

### Don't

- 不执行全库 DELETE / DETACH DELETE（含 `MATCH (n:Novel) DELETE n`）
- 不跨 novel_id 查询或清理 Person
- 不在 diagnose 模式修改代码/数据/配置
- 不依赖「数据库初始为空」
- 不把一次真实 LLM 评估当成 deterministic 测试
- 不把 LLM 非确定性（judge 判定、提取输出）当确定性结果写死进测试
- 不把「LLM 不稳定」当单一问题：先区分 非确定性(P06)/限流(P05)/欠费(P04)/候选召回(P08)/mention hygiene(P09)
- **不把「429 根因=concurrency=4」当事实**（已证伪，见 P005）
- **不把 ER 失败一律归因于 judge**（P06 ≠ P04/P05/P08/P09）

---

## 1. Diagnostic Routing（症状 → 第一检查位置）

> **规则**：遇到症状必须优先查此表定位 First Check，再读对应 Problem Record。**不要凭经验直接修改代码。**

| Symptom | First Check | Problem(s) |
|---|---|---|
| HTTP 429 / limit_requests | `[llm] stage/status/code/body` + 账户状态 | P04 / P05 |
| HTTP 400 / Arrearage | 账户欠费状态（充值，不改代码） | P04 |
| 大量 LLM 调用同时失败 | `[llm]` 日志 code → 账户 → 限流 | P04 / P05 / P07 |
| 同一人物出现多个 Person 节点 | canonical / alias / bridge evidence（重放） | P08 |
| `'大老' IN p.aliases` 无记录但人物存在 | canonical 自身不在 aliases → 分裂机制 | P08 |
| Person aliases 出现「两个儿子」「年青人」等集合/泛指词 | mention category / extraction 输出 / hygiene | P09 |
| 大量错误合并 | P09（集合 canonical）→ P08（候选扩散）→ P06（judge） | P09 / P08 / P06 |
| 同样 judge 输入不同结果 | 重放 / 多次 evaluation（非单次结论） | P06 |
| 测试后 Novel 消失 | 检查 destructive query（grep DELETE n） | P01 |
| 重启后小说消失 | `GET /api/novels` / startup restore（进程内 JobStore 限制） | 相关文档（见 P13 经验） |
| 全 chunk failed 但 job completed_with_errors | job terminal state 判定 | P11 |
| 未知 mention 候选随顺序变化 | chunk 预扫描是否在 resolve 开头 | P10 |
| failed_blocks 只有 unexpected:LLMError | `[llm]` 日志 status/body | P07 |

---

## 2. Problem Index

| ID | Problem | Domain | Status | Severity | Evidence | Detailed Doc |
|----|---------|--------|--------|----------|----------|--------------|
| P01 | 测试全库删除 Novel → 孤儿数据 | Neo4j 数据安全 | ✅ | Critical | HIGH | [P001](docs/problems/P001-neo4j-full-delete.md) |
| P02 | 共享 Neo4j 实例混入业务数据 | Neo4j 数据安全 | ✅ | High | HIGH | — |
| P03 | 计划测试与实现语义互斥 | 测试与流程 | ✅ | Medium | HIGH | — |
| P04 | 百炼账号欠费（Arrearage） | LLM / API | ✅ | High | MEDIUM | [P004](docs/problems/P004-llm-account-arrearage.md) |
| P05 | 429 限流诊断规则（limit_requests） | LLM / API | ✅ | High | MEDIUM | [P005](docs/problems/P005-llm-ratelimit.md) |
| P06 | Judge 判定非确定性 + 过度合并 | LLM / ER | 🔍 | High | MEDIUM | [P006](docs/problems/P006-judge-nondeterminism.md) |
| P07 | LLM 4xx 状态码被吞 | LLM / API | ✅ | Medium | HIGH | — |
| P08 | Entity Resolution：zero-overlap 分裂与 canonical 合并质量 | ER 算法 | 🔍 | High | HIGH | [P008](docs/problems/P008-zero-overlap-entity-split.md) |
| P09 | Mention Hygiene：集合/泛指 mention 污染 Person 实体 | ER 算法 | 🔍 | **High** | HIGH | [P009](docs/problems/P009-mention-hygiene.md) |
| P10 | 同 chunk 共现召回顺序敏感 | ER 算法 | ✅ | High | HIGH | [P010](docs/problems/P010-cooccurrence-order-sensitivity.md) |
| P11 | 全 chunk 失败 job 状态应为 failed | 流程 / 状态机 | 🔍 | Medium | HIGH | [P011](docs/problems/P011-all-chunks-failed-status.md) |
| P12 | 沙箱/环境限制清单 | 环境与沙箱 | ✅ | Medium | HIGH | — |
| P13 | 脚本超时杀 + stdout 缓冲丢输出 | 环境与沙箱 | ✅ | Low | HIGH | — |
| P14 | 依赖/驱动 API 坑汇总 | 基础设施 | ✅ | Medium | HIGH | — |

---

## 3. Active Problems（🔍 investigating）

> 尚未闭环。遇到相关 Trigger 先走 §1 Routing，再读详细文档。

### P06 — Judge 判定非确定性 + 过度合并

- **Trigger**: 同样 judge 输入不同结果；两次 ingest 不一致；人物节点出现泛指词
- **区分**: 非确定性(P06) vs 限流(P05) vs 欠费(P04) vs 候选召回(P08) vs mention hygiene(P09)——先看 `[llm]` 日志 code
- **当前状态**: judge 为唯一合并决策点；测试 mock；评估多次取趋势；**不把所有 ER 失败归因于 P06**
- → [P006 完整记录](docs/problems/P006-judge-nondeterminism.md)

### P08 — Entity Resolution：zero-overlap 分裂与 canonical 合并质量

- **Trigger**: 同一人物多个节点；桥接名（天保大老）存在却未合并；大量错误合并（先 P09 后 P08）
- **当前状态**: 多层修复已落地（pre-scan → text recall → strong ranking → canonical merge）；V0.2.3 false merge 主因 P09；V0.2.4 后待真实评估验证
- → [P008 完整记录](docs/problems/P008-zero-overlap-entity-split.md)

### P09 — Mention Hygiene：集合/泛指 mention 污染 Person 实体

- **Trigger**: aliases 出现「两个儿子」「年青人」等集合/泛指词；mention_count 异常高
- **当前状态**: V0.2.4 已实现（MentionCategory + hygiene.py + resolver 决策表，128 unit / 15 integration）；**真实《边城》验证待执行**
- → [P009 完整记录](docs/problems/P009-mention-hygiene.md)

### P11 — 全 chunk 失败 job 状态应为 failed

- **Trigger**: job 状态 `completed_with_errors` 但 failed_blocks = 总 chunk 数
- **当前状态**: 终态判定缺「全部失败 → failed」分支，代码变更未授权
- → [P011 完整记录](docs/problems/P011-all-chunks-failed-status.md)

---

## 4. Resolved Problems（摘要）

> 已解决/已定论问题摘要。若症状再次出现，先读对应记录的「Do Not Reopen」检查代码回退/环境变化，**不要盲目重复旧修复**。

- **P01** 测试全库删除 Novel → 孤儿数据（329 孤儿 Person + 577 边）。修复：删除一律 `db.delete_novel(novel_id)`；测试独立 novel_id 自建自清；空列表非破坏性断言。`a534116`。[详细](docs/problems/P001-neo4j-full-delete.md)
- **P02** 共享 Neo4j 实例混入约 4.8 万医疗节点。修复：独立 `novel-neo4j`（卷 `novel_neo4j_data`），共享栈 `restart=no`。`a534116`
- **P03** 计划测试与「known 整本持续」语义互斥。修复：以 spec 语义为准修订测试。`f3baf2a`
- **P04** 百炼账号欠费（Arrearage）：全部调用 400。处理：`[llm]` 日志 code 区分；找用户充值不改代码。[详细](docs/problems/P004-llm-account-arrearage.md)
- **P05** 429 限流诊断规则：**不是「并发 4 导致限流」**——历史事故受账户状态混淆，concurrency=4 账号正常时可运行；遇到 429 先查 code+账户再做 A/B。[详细](docs/problems/P005-llm-ratelimit.md)
- **P07** LLM 4xx 状态码被吞。修复：`[llm]` 日志记录 status/body（不含 key）。`36e8019`
- **P10** 同 chunk 共现顺序敏感。修复：chunk 预扫描。`c850bda`。[详细](docs/problems/P010-cooccurrence-order-sensitivity.md)
- **P12** 沙箱限制：pip / pytest tmp_path / vite spawn。处理：`backend/.deps` 注入、BytesIO 不落盘、唯一 basetemp、node_modules 补丁。`3267755` 系
- **P13** 轮询脚本被工具超时杀 + stdout 缓冲丢输出。处理：`python -u` + 后台任务
- **P14** 依赖/驱动 API 坑：缺 Authorization 头（`8c25836`）/ ResultConsumedError（`dcf6023`）/ Neo4j 属性不支持 map（`dcf6023`）/ ebooklib 无 get_title（`f2b03c6`）

---

## 5. Problem Records Directory

> 完整 forensic / postmortem / engineering record。每个记录统一 20 字段模板：
> Status / Severity / Domain / Tags / First Seen / Last Verified / Evidence Level / Decision Type /
> Related Problems / Related Commits / Related Evaluation Reports /
> Context / Symptom / Impact / Trigger / Timeline / Initial Hypothesis / Investigation Path /
> Experiments / Evidence / Root Cause / Ruled-out Causes / Failed Approaches / Correct Approach /
> Invariants / Validation / Trade-offs / Decision / Follow-up / Current Limitation / Do Not Reopen。

| 记录 | 问题 |
|---|---|
| [P001-neo4j-full-delete.md](docs/problems/P001-neo4j-full-delete.md) | P01 测试全库删除事故 |
| [P004-llm-account-arrearage.md](docs/problems/P004-llm-account-arrearage.md) | P04 百炼账号欠费 |
| [P005-llm-ratelimit.md](docs/problems/P005-llm-ratelimit.md) | P05 429 限流诊断规则 |
| [P006-judge-nondeterminism.md](docs/problems/P006-judge-nondeterminism.md) | P06 judge 非确定性 |
| [P008-zero-overlap-entity-split.md](docs/problems/P008-zero-overlap-entity-split.md) | P08 ER 分裂与合并质量 |
| [P009-mention-hygiene.md](docs/problems/P009-mention-hygiene.md) | P09 mention hygiene 污染 |
| [P010-cooccurrence-order-sensitivity.md](docs/problems/P010-cooccurrence-order-sensitivity.md) | P10 共现顺序敏感 |
| [P011-all-chunks-failed-status.md](docs/problems/P011-all-chunks-failed-status.md) | P11 全 chunk 失败状态 |

**中短问题（P02/P03/P07/P12/P13/P14）**：无独立文档，完整记录保留在本文件 §4 摘要 + AGENTS.md/TESTING.md 对应规则中。

**Evaluation Reports**（`docs/evaluation/`）：
- `2026-08-21-biancheng-er-eval.md`（《边城》ER 评估）
- `2026-08-21-biancheng-er-stability.md`（稳定性评估，P06 证据源）
