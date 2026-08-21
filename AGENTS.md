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

### problem.md

项目长期问题知识库。

记录：

* Bug
* 根因
* 解决方案
* 验证结果
* 工程事故
* 环境问题
* 限制与经验

任何非 trivial 的问题解决后必须更新 `problem.md`。

---

# 3. Before Starting a Task

开始任何开发或 Debug 任务之前：

1. 阅读 `AGENTS.md`
2. 阅读 `problem.md`
3. 根据任务类型阅读：

   * UI → `DESIGN.md`
   * 测试 / Evaluation → `TESTING.md`
4. 检查当前 Git 工作区：

   * `git status`
   * 相关 `git diff`
5. 不假设工作区是干净的。
6. 不覆盖其他 Agent 已有修改。

如果发现当前任务与 `problem.md` 中已有问题相关，优先遵循已有解决方案和限制。

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

每次解决一个非 trivial 问题后：

1. 更新 `problem.md`
2. 记录：

   * Problem
   * Root Cause
   * Why
   * Solution
   * Validation
   * Trade-offs
   * Git commit
3. 如果问题仍未完全解决，状态标记为：
   `investigating`

不得把未经验证的猜测写成最终根因。

不得删除历史问题记录。

---

# 11. Documentation Consistency

当问题产生新的长期规则时：

* `problem.md` 记录事故和历史
* `TESTING.md` 记录测试规则
* `DESIGN.md` 记录视觉规则
* `AGENTS.md` 记录 Agent 必须遵守的长期工程规则

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
6. 是否更新 `problem.md`

---

# 14. Default Principle

核心原则：

> Diagnose first.
> Change minimally.
> Verify explicitly.
> Record important problems.
> Never destroy unrelated data.
