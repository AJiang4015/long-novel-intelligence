# AGENTS.md

## 1. Project Overview

Project: Long-Novel-Intelligence

Purpose:

基于 EPUB 长篇小说进行人物实体抽取、实体消歧、人物关系构建与关系图可视化。

Current stack:

* Backend: FastAPI + Python
* Frontend: React + Vite + TypeScript
* Graph database: Neo4j Community 5.26.x
* LLM: configurable cloud API
* Frontend graph rendering: custom SVG GraphCanvas
* Deployment: backend/frontend local development + dedicated Neo4j Docker container

---

# 2. Source of Truth

项目包含以下长期维护文档，各自职责不同：

### DESIGN.md

UI/UX 和 Design System 的唯一事实来源。

涉及：

* colors
* typography
* spacing
* layout
* components
* graph visualization
* states
* visual restrictions

任何前端 UI 修改必须遵循 `DESIGN.md`。

---

### TESTING.md

测试与真实评估规范。

涉及：

* unit tests
* integration tests
* real LLM evaluation
* test data isolation
* database cleanup
* regression testing
* evaluation reporting

任何新增测试必须遵循 `TESTING.md`。

---

### PROBLEM.md

项目长期问题知识库：**PROBLEM.md = 问题地图 + 诊断路由**（症状→第一检查位置），`docs/problems/` 存放完整 Problem Record（20 字段模板），`docs/evaluation/` 存放真实数据实验记录（Problem Record 只引用）。

记录：

* Bug
* 根因
* 解决方案
* 验证结果
* 工程事故
* 环境问题
* 限制与经验

任何非 trivial 的问题解决后必须更新 `PROBLEM.md` 或对应 `docs/problems/*.md`。

---

# 3. Before Starting a Task

开始任何开发或 Debug 任务之前：

1. 阅读 `AGENTS.md`
2. 阅读 `PROBLEM.md`
3. 根据任务类型阅读：

   * UI → `DESIGN.md`
   * 测试 / Evaluation → `TESTING.md`
4. 检查当前 Git 工作区：

   * `git status`
   * 相关 `git diff`
5. 不假设工作区是干净的。
6. 不覆盖其他 Agent 已有修改。

如果发现当前任务与 `PROBLEM.md` 中已有问题相关，优先遵循已有解决方案和限制。

---

# 4. Scope Control

默认采用最小修改原则：

* 只修改完成当前任务所必需的文件
* 不顺手重构无关模块
* 不主动升级依赖
* 不主动替换技术栈
* 不增加未请求的新功能
* 不修改已经稳定的 API / DTO / 数据模型，除非任务明确要求
* 不因为 UI 需求而修改后端业务逻辑
* 不因为 Bug 修复而顺手重构整个模块

如果发现需要扩大范围，先说明原因和影响。

---

# 5. Bug Investigation

项目使用 `bug-investigation` skill 处理 Bug。

默认模式：

`diagnose`

diagnose 模式：

* 只读
* 不修改源码
* 不修改数据库
* 不修改配置
* 不删除数据
* 不安装依赖

必须：

* 复现问题
* 查找证据
* 区分症状、直接原因、根因
* 给出修复方案
* 说明验证方法

只有用户明确要求修复时，才进入 fix 模式。

---

# 6. Code Changes

进行代码修改时：

1. 先说明准备修改的范围
2. 保持 API 和 DTO 向后兼容
3. 优先复用现有组件和模块
4. 使用当前项目已有依赖
5. 修改完成后运行相关测试
6. 运行项目 build / type check
7. 报告修改文件与验证结果

不要为了“代码更漂亮”而改变已经稳定的业务行为。

---

# 7. Neo4j Safety Rules

当前项目使用独立的小说 Neo4j 实例。

小说项目数据库只负责：

* `Novel`
* `Person`
* `RELATES_TO`

严禁触碰其他业务 Neo4j 实例或数据。

禁止：

```cypher
MATCH (n) DELETE n
MATCH (n) DETACH DELETE n
MATCH (n:Novel) DELETE n
```

这种无范围 destructive query。

所有数据删除必须：

* 明确指定 `novel_id`
* 优先复用 `db.delete_novel(novel_id)`
* 删除前确认目标范围

测试不得清空整个数据库。

任何数据库修复操作都必须明确获得用户授权。

---

# 8. Test Data Isolation

自动化测试必须：

1. 创建属于自己的 `novel_id`
2. 只操作自己的测试数据
3. 测试结束后只清理自己的 `novel_id`
4. 不删除用户真实上传的 Novel
5. 不依赖数据库“初始为空”

禁止：

```cypher
MATCH (n:Novel) DELETE n
```

作为测试清理方式。

真实 LLM Evaluation 使用新的 Novel ID，不复用历史实验数据。

---

# 9. Real LLM Evaluation

真实 LLM 测试与自动化 pytest 分离。

每次真实 Evaluation 必须记录：

* Git commit
* Novel ID
* 小说
* LLM model
* chunk size
* overlap
* concurrency
* Neo4j version
* 结果统计
* failure statistics

真实 LLM Evaluation 默认不删除结果。

不得把一次真实 Evaluation 当成 deterministic unit test。

---

# 10. Problem Knowledge Base

`PROBLEM.md` 是**问题知识库**，不是流水账/档案索引。目的是让 Agent 遇到类似现象时能快速判断「先查什么、不做什么、怎么处理」。

## 记录标准

**必须记录**（满足任一条）：

* 造成数据损坏/丢失风险
* 需要花时间排查、根因不明显
* 可能再次发生（尤其 Agent 很容易重复犯）
* 有架构/工程决策（含权衡）
* 外部服务/环境限制（账号、沙箱、限流）
* 性能/并发问题
* LLM 特有行为（非确定性、欠费、限流、畸形输出）

**不需要记录**：

* 拼写错误、一眼可见的语法错误、临时 typo
* 改一个变量名
* 普通 UI 微调

## 条目结构

`PROBLEM.md` 是**问题地图 + 诊断路由**（§1 Diagnostic Routing 症状→第一检查位置；§2 Index；§3 Active；§4 Resolved；§5 Records Directory）。完整 Problem Record 存放在 `docs/problems/PXXX-*.md`，统一 20 字段模板：Status / Severity / Domain / Tags / First Seen / Last Verified / Evidence Level（HIGH/MEDIUM/LOW）/ Decision Type（FACT/HYPOTHESIS/EXPERIMENT_RESULT/DESIGN_DECISION/KNOWN_LIMITATION）/ Related Problems / Related Commits / Related Evaluation Reports / Context / Symptom / Impact / Trigger / Timeline / Initial Hypothesis / Investigation Path / Experiments / Evidence / Root Cause / Ruled-out Causes / Failed Approaches / Correct Approach / Invariants / Validation / Trade-offs / Decision / Follow-up / Current Limitation / Do Not Reopen。

摘要与索引条目保持简洁（PROBLEM.md 只承载地图 + 摘要，不承载事故过程）。

## Agent 使用要求

* 开发/Debug 前先读取 `PROBLEM.md`
* **遇到症状先走 §1 Diagnostic Routing**，根据 First Check 定位，再读对应 `docs/problems/PXXX-*.md` 的 Investigation Path 与 Failed Approaches，**不要凭经验直接修改代码**
* 解决非 trivial 问题后更新对应 Problem Record（PROBLEM.md 摘要 + docs/problems 详细记录）
* 不覆盖历史事实：只增改，不删除/改写已确认的根因、方案、commit、被证伪假设
* 已 resolved 问题若再次出现同样症状，先检查旧解决方案是否回退、环境是否变化、输入是否变化或出现新的 reproduction（见各记录「Do Not Reopen」），**不得盲目重复旧修复**

## Problem Knowledge Rule

1. 开发/Debug 前先阅读 `PROBLEM.md`（§1 Routing + §2 Index）。
2. 遇到已知 Trigger 时，先读取对应 `docs/problems/Pxxx-*.md`。
3. Diagnose 模式只修改诊断文档，不修改代码/数据。
4. Fix 完成后必须更新对应 Problem Record（含 Validation 与 Do Not Reopen）。
5. 新增问题必须区分 Decision Type：FACT / HYPOTHESIS / EXPERIMENT_RESULT / DESIGN_DECISION / KNOWN_LIMITATION。
6. **不删除被证伪假设**（写入 Ruled-out Causes，防止后续 Agent 重复调查）。
7. 不覆盖历史实验结果。
8. 不把单次真实 LLM evaluation 当 deterministic fact（Evidence Level 区分 HIGH/MEDIUM/LOW）。
9. Resolved 问题再次出现，先检查：code regression / environment change / model change / input change，不得直接重复旧修复。
10. Problem Record 必须记录 Validation 和 Do Not Reopen。

---

# 11. Documentation Consistency

当问题产生新的长期规则时：

* `PROBLEM.md` 记录事故、根因与「以后怎么办」（知识库）
* `TESTING.md` 记录测试规则
* `DESIGN.md` 记录视觉规则
* `AGENTS.md` 记录 Agent 必须遵守的长期工程规则（含高频 Do / Don't）

不要把所有内容都堆进单个文件。

---

# 12. Git

修改前检查：

```bash
git status
```

修改后检查：

```bash
git diff
```

不要：

* `git reset --hard`
* 删除他人未提交修改
* 擅自 force push

完成一个独立功能或问题修复后，建议形成独立 commit。

---

# 13. Final Verification

完成任务前至少：

* 运行与修改相关的测试
* 运行项目 build / type check
* 检查 git diff
* 确认没有修改任务范围之外的文件

最终报告：

1. 修改内容
2. 修改文件
3. 测试结果
4. build 结果
5. 任何已知限制
6. 是否更新 `PROBLEM.md`

---

# 14. Default Principle

核心原则：

> Diagnose first.
> Change minimally.
> Verify explicitly.
> Record important problems.
> Never destroy unrelated data.

---

# 15. Do / Don't（高频踩坑速查）

> 详细根因与「以后怎么办」见 `PROBLEM.md`。此表用于开工前快速过一遍，避免重复踩坑。

## Do

* 删除数据一律 `db.delete_novel(novel_id)`（按 id 精确，删除前 dry-run 列目标）
* 每个测试用例创建独立 `novel_id`，结束后只清理自己的
* `EntityResolver` 一次 ingest 一个实例（`known`/mention index 整本持续）
* 长任务脚本用 `python -u`（无缓冲）+ 后台任务方式运行
* 真实 LLM 评估前记录 Environment Baseline（commit/model/chunk/concurrency/novel_id/Neo4j 版本）
* 修改 `resolver.py` 后跑 `test_resolver.py` 回归清单（TESTING.md §8）
* LLM 调用报错时先看诊断日志 `[llm] stage=... status=... code=...`（区分 Arrearage/限流/validation）
* 改 `.env` 后必须重启后端（settings 进程内缓存）

## Don't

* 不执行全库 DELETE / DETACH DELETE（含 `MATCH (n:Novel) DELETE n`）
* 不跨 novel_id 查询或清理 Person
* 不在 diagnose 模式修改代码/数据/配置
* 不依赖「数据库初始为空」
* 不把一次真实 LLM 评估当成 deterministic 测试
* 不为「代码更漂亮」改动已稳定的 API / DTO / 行为
* 不把 LLM 的非确定性（judge 判定、提取输出）当成确定性结果写死进测试
