# PROCESS.md — 项目开发 / 问题修复 / 实验 / 验收流程

> 定位：**应该怎么工作**——描述「任务怎么做」，不解释「为什么这么设计」（为什么见 `DECISIONS.md`，系统怎么组织见 `ARCHITECTURE.md`）。
> 规则（必须遵守什么）见 `AGENTS.md`；测试/评估参数与模板见 `TESTING.md`。

---

## 0. 流程总览

```text
Problem
  ↓
Evidence
  ↓
Problem classification / layer attribution
  ↓
Spec
  ↓
Review
  ↓
Implementation
  ↓
Unit
  ↓
Integration
  ↓
Real LLM evaluation
  ↓
Evaluation report
  ↓
Decision
  ↓
Commit
```

每个环节必须完成后才进入下一步；**不允许跳级**（尤其：不能没有 Evidence 就归因，不能没有 Review 就实现，不能没有 Real evaluation 就下结论）。

**闭环**：Evaluation report 回写 Problem Record（补充 Evidence，不覆盖历史事实），可能触发新一轮 Problem 立项——流程是循环而非一次性的。

## 1. 问题处理流程（Problem → Evidence → 归因）

1. **Problem**：记录症状与影响（`PROBLEM.md` 问题地图；完整记录入 `docs/problems/PXXX-*.md`）。
2. **Evidence**：先查 `PROBLEM.md` §1 Diagnostic Routing 定位 First Check，再读对应 Problem Record 的 Investigation Path 与 Failed Approaches；复现问题、收集证据（数据库查询 / 文本定位 / 代码路径 / lineage）。**不要凭经验直接修改代码。**
3. **Problem classification / layer attribution**：区分 症状 / 直接原因 / 根因；把问题归到**真正拥有该决策的层**，不是「哪里方便改就改哪里」。六类归因链（extraction coverage ≠ recall ≠ judge ≠ admission ≠ registration ≠ merge）与各层问题映射见 `backend/app/pipeline/PIPELINE_LAYER.md` §4。

   归因手段：lineage 观测（`ER_LINEAGE=1` + `backend/tools/diagnose_lineage.py` 离线归层）优先；无观测时先补观测再归因（D-11：Task A 先于 Task B）。
4. **Spec**：基于归因写设计（`docs/superpowers/specs/`），明确改哪一层、不动哪一层、验证方法。
5. **Review**：实现前评审（含 Do Not Reopen 检查：是否已有同类记录、旧方案是否被证伪、是否在重复旧修复）。
6. **Decision**：问题闭环后，若产生长期决策登记 `DECISIONS.md`；若只是实验结论，入 `docs/evaluation/`，**不升级为永久 Decision**。

## 2. 真实 LLM 实验规范

- **变量固定原则**：一次实验只允许一个变量变化。除被测变量外，以下必须全部固定：输入语料内容（同一本小说 / 同一份 EPUB）、模型、chunk size、overlap、concurrency、代码 commit、Neo4j 版本、相关环境变量（`.env` 差异需在报告中声明）。
- **fresh novel / fresh job 要求**：每次真实评估使用**全新 novel_id**（新上传），绝不复用旧 Novel 增量测试；评估结果默认不删除。**注意**：novel_id 是技术标识而非实验变量——fresh-novel 纪律下 A/B 两组必然持有不同 novel_id（同一份 EPUB 重新上传），因此 novel_id 不进「变量固定」清单，只要求**输入语料内容一致**。
- **A/B 实验唯一变量**：A/B 两组对比时，除被测变量（有且仅有一个）外，其余按「变量固定原则」全部相同——同一输入语料内容、相同模型 / 切块 / 并发 / 代码版本 / Neo4j 版本 / 环境。被测变量及其取值在报告中显式声明（哪个是 A、哪个是 B、差异是什么）。
- **LLM 非确定性**：judge / 抽取存在非确定性（P06），单组单次运行不能代表结论；A/B 结论需每组多次运行取趋势，并在报告中注明运行次数与波动（见 `TESTING.md` §9.1）。
- **验收顺序（不得跳级）**：unit（全 mock）→ integration（真实 Neo4j + mock LLM）→ real ingest（真实 LLM）。
- **lineage 使用**：归因类实验开启 `ER_LINEAGE=1`（默认关零开销）；事件经 `lineage_id` join，job 终态 flush 后离线归层；观测是旁路，**不得**因观测改变判定。
- 评估参数 / 报告模板 / 验收指标见 `TESTING.md` §6/§9。

## 3. 问题立项与提交纪律

- 一个行为问题一个独立立项（独立 Problem Record）；机制 A 成功 + 机制 B 失败必须分别立项（D-12）。
- **一个问题一个独立 commit**；commit 前 `git diff` 审阅，只包含该问题相关文件。
- 禁止：`git reset --hard`、删除他人未提交修改、擅自 force push（`AGENTS.md` §4）。

## 4. 修改与验收流程

**修改前**：
1. `git status` / 相关 `git diff`；不假设工作区干净。
2. 按 `AGENTS.md` §1 读必读文档；按任务类型读 `TESTING.md` / `DESIGN.md`。
3. 先说明准备修改的范围；保持 API 和 DTO 向后兼容；优先复用现有组件。

**修改后**：
1. 运行相关测试（unit → integration，见 `TESTING.md`；纯文档变更可跳过，见 `AGENTS.md` §5 docs-only 例外）；
2. 运行 build / type check；
3. `git diff` 检查；确认没有修改任务范围之外的文件；
4. 按以下报告模板交付：

```text
1. 修改内容
2. 修改文件
3. 测试结果
4. build 结果
5. 任何已知限制
6. 是否更新 PROBLEM.md
```

## 5. 核心组件修改准入（prompt / resolver / schema / merger 等）

- **前置条件（缺一不可）**：
  1. 存在 Problem Record（Evidence 已收集、层归属已定）；
  2. 存在 Spec（`docs/superpowers/specs/`）并说明影响面；
  3. 经过 Review（含 Do Not Reopen 检查）。
- 未经归因的修改禁止；临时结论不得直接进入实现。
- 冻结组件（如 P16-b，`DECISIONS.md` D-6）需先解除冻结（独立设计 + 评审）才能改。

## 6. 失败归因与止损

- **归因失败**：多轮尝试无新证据时回到 Evidence（补观测 / 重放 / 检查输入），**停止继续无依据修改**。
- **复发处理**：已 resolved 问题再次出现同样症状，先检查：code regression / environment change / model change / input change（对应记录「Do Not Reopen」），**不得盲目重复旧修复**。
- **判定类失败**：LLM 判定非确定性（judge / extraction）不能当 deterministic 结论；评估多次取趋势、单次结果不写死进测试（实验规范见 §2「LLM 非确定性」）。

## 7. 固化优先级原则

```text
Task A 先于 Task B        （归层/观测先于修复设计）
Problem 先于 Code         （先立项，后动手）
Evidence 先于 Root Cause  （先有证据，后定根因）
Real evaluation 先于结论  （真实评估通过后才下结论）
```
