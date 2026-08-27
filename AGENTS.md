# AGENTS.md — Agent 工作规则 / 项目硬约束

> 定位：**Agent 宪法**——只保留必须长期遵守、跨任务有效、违反后会直接导致项目不正确的规则。
> 任务怎么做见 `PROCESS.md`；决定了什么、为什么见 `DECISIONS.md`；系统怎么组织见 `ARCHITECTURE.md`；每层负责什么见 `backend/app/*/*_LAYER.md`。

---

## 0. 文档地图（谁管什么）

| 文档 | 管什么 |
|---|---|
| `AGENTS.md`（本文件） | Agent 必须遵守的硬规则（宪法） |
| `PROCESS.md` | 任务应该怎么做（流程 / 实验纪律 / 准入 / 止损） |
| `DECISIONS.md` | 已做出的长期决策及理由（Decision Record） |
| `ARCHITECTURE.md` | 系统怎么组织（数据流 / 依赖方向 / 边界） |
| `backend/app/{api,db,models,pipeline,schemas}/*_LAYER.md` | 每层负责什么、不能负责什么（Layer Contract） |
| `PROBLEM.md` | 哪里有问题（问题地图 + 诊断路由）；完整记录在 `docs/problems/PXXX-*.md` |
| `docs/superpowers/specs/` | 准备怎么改（Design Spec）；`docs/superpowers/plans/` 实施计划 |
| `docs/evaluation/` | 改完真实发生了什么（真实 LLM 评估报告） |
| `TESTING.md` | 测试与真实评估规范（参数 / 模板 / 回归清单） |
| `DESIGN.md` | UI/UX 和 Design System 的唯一事实来源 |

**新增文档先判断属于哪一类**（规则 / 流程 / 决策 / 架构 / 层契约 / 问题 / Spec / Evaluation），不要继续把所有内容追加到本文件。

---

## 1. 开工前必读

开始任何开发或 Debug 任务之前：

1. 阅读 `AGENTS.md`
2. 阅读 `PROBLEM.md`
3. 根据任务类型阅读：

   * UI → `DESIGN.md`
   * 测试 / Evaluation → `TESTING.md`
   * 流程 / 实验 → `PROCESS.md`
   * 架构 / 边界 → `ARCHITECTURE.md` 与对应 `*_LAYER.md`
4. 检查当前 Git 工作区：`git status`、相关 `git diff`
5. 不假设工作区是干净的；不覆盖其他 Agent 已有修改。

问题知识库硬规则（详细规范见 `PROBLEM.md`）：

* 遇到症状先走 `PROBLEM.md` §1 Diagnostic Routing，读对应 `docs/problems/PXXX-*.md` 的 Investigation Path 与 Failed Approaches，**不要凭经验直接修改代码**
* 解决非 trivial 问题后必须更新对应 Problem Record（PROBLEM.md 摘要 + docs/problems 详细记录）
* 不覆盖历史事实：只增改，不删除/改写已确认的根因、方案、commit、被证伪假设
* 不把单次真实 LLM evaluation 当 deterministic fact（Evidence Level 区分见 `PROBLEM.md` §6 Rule 8）
* 已 resolved 问题再次出现同样症状，先检查 code regression / environment change / model change / input change（见各记录「Do Not Reopen」），**不得盲目重复旧修复**

---

## 2. 硬性禁止与边界

### 数据安全（违反即造成数据损坏/丢失风险）

* 禁止无范围 destructive query：

  ```cypher
  MATCH (n) DELETE n
  MATCH (n) DETACH DELETE n
  MATCH (n:Novel) DELETE n
  ```

* 所有数据删除必须：明确指定 `novel_id`、优先复用 `db.delete_novel(novel_id)`、删除前确认目标范围（dry-run 列目标）
* 禁止跨 novel_id 查询或清理 Person
* 小说项目数据库只负责 `Novel` / `Person` / `RELATES_TO`；严禁触碰其他业务 Neo4j 实例或数据
* 任何数据库修复操作都必须明确获得用户授权
* 不依赖「数据库初始为空」

### 诊断与修改纪律

* 默认采用最小修改原则：只修改完成当前任务所必需的文件；不顺手重构无关模块；不主动升级依赖 / 替换技术栈；不增加未请求的新功能；如果发现需要扩大范围，先说明原因和影响
* `bug-investigation` skill 默认 `diagnose` 模式：只读，不修改源码/数据库/配置，不删除数据，不安装依赖；只有用户明确要求修复时才进入 fix 模式
* 保持 API 和 DTO 向后兼容；不为「代码更漂亮」改变已经稳定的 API / DTO / 数据模型 / 业务行为
* 不因为 UI 需求而修改后端业务逻辑；不因为 Bug 修复而顺手重构整个模块

### 决策红线（详见 `DECISIONS.md`）

* **不把「父亲/母亲/祖父」加入 generic 词表**（D-7：P16/P18 是 context / relational-role 问题，正文真实人物；RC3 已锁）
* **不引入 classifier 绕过 P017 D5**（D-10：D5 缺口——原义 category=None→PERSON fallback 与 D5-a extraction 覆盖缺失为 Known Limitation；D5-b 已由 B-1 结构规则修复（V0.2.8，D-17）；任何绕过仍禁止，走 P06 follow-up）
* **不因「顺顺→父亲 正文内吸收仍存在」判 P16-a/P17 失败**（P18 独立问题；角色称谓吸收语义可能正确，先做 aliases 可解释性核对）
* **不把「DESCRIPTIVE/COMPOSITE 无法确认 → unresolved 不注册」当回归**（D-9：P017 D2 有意取代 P009「不静默丢人物」兜底；`test_hygiene.py:176` 已修订）
* **lineage 只允许作为旁路 observer**（D-8：不参与判定、不改写任何输出）
* **P16-b 已冻结**（D-6）：不要为「爸爸 未 confirmed」「翠翠的祖父 未建立」修改 P16-b gate
* 问题归因到**拥有该决策的层**（extraction ≠ recall ≠ judge ≠ admission ≠ registration ≠ merge，见 `PIPELINE_LAYER.md` §4），不是哪里方便改就改哪里

---

## 3. 测试与评估铁律

* 自动化测试必须：创建属于自己的 `novel_id`；只操作自己的测试数据；测试结束后只清理自己的 `novel_id`；不删除用户真实上传的 Novel；不依赖数据库「初始为空」；禁止用 `MATCH (n:Novel) DELETE n` 作为测试清理方式
* 真实 LLM Evaluation 使用**新的 Novel ID**，不复用历史实验数据；真实评估默认不删除结果
* 真实 LLM 测试与自动化 pytest 分离；**不得把一次真实 Evaluation 当成 deterministic unit test**；不把 LLM 非确定性（judge 判定、提取输出）当确定性结果写死进测试
* 每次真实评估必须记录 Environment Baseline（commit / model / chunk size / overlap / concurrency / novel_id / Neo4j 版本），细节与报告模板见 `TESTING.md` §6/§9
* **评估报告声明（强制）**：报告标题与顶部必须注明「本报告是 XX 版本的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record」
* 回归纪律（以 `TESTING.md` §8 为准）：修改 `resolver.py` 后跑 resolver/hygiene/sections 相关回归；修改 ER 相关代码后跑全量 unit + integration

运行纪律：

* 长任务脚本用 `python -u`（无缓冲）+ 后台任务方式运行
* LLM 调用报错时先看诊断日志 `[llm] stage=... status=... code=...`（区分 Arrearage / 限流 / validation）
* 改 `.env` 后必须重启后端（settings 进程内缓存）
* `EntityResolver` 一次 ingest 一个实例（`known` / mention index 整本持续）

---

## 4. Git 约束

修改前检查 `git status`；修改后检查 `git diff`。

禁止：

* `git reset --hard`
* 删除他人未提交修改
* 擅自 force push

完成一个独立功能或问题修复后，形成独立 commit（**一个问题一个 commit**，见 `PROCESS.md` §3）。

---

## 5. 收尾必做（Final Verification）

完成任务前至少：

* 运行与修改相关的测试
* 运行项目 build / type check
* 检查 git diff
* 确认没有修改任务范围之外的文件

**例外（docs-only）**：纯文档变更（不涉及代码 / 测试 / prompt / 配置 / 数据）可跳过「运行测试」与「build / type check」，但仍必须执行后两项（git diff 检查 + 范围确认），并在最终报告中注明「本轮为文档变更，未运行测试 / build」。

最终报告包含：1. 修改内容 2. 修改文件 3. 测试结果 4. build 结果 5. 任何已知限制 6. 是否更新 `PROBLEM.md`。

---

## 6. 默认原则

> Diagnose first.
> Change minimally.
> Verify explicitly.
> Record important problems.
> Never destroy unrelated data.
