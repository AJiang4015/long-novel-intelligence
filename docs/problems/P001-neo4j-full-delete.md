# P01 — Neo4j 测试全库删除 Novel → 孤儿数据事故

- **Status**: ✅ resolved
- **Severity**: Critical（真实数据丢失）
- **Domain**: Neo4j 数据安全
- **Tags**: destructive-query, test-isolation, data-loss
- **First Seen**: V0.1 集成测试阶段
- **Last Verified**: `a534116` 修复后回归通过
- **Evidence Level**: HIGH（事故现场数据 + 修复后回归可稳定验证）
- **Decision Type**: FACT（事故证据）+ DESIGN_DECISION（删除必须走 db.delete_novel）
- **Related Problems**: P02（共享实例隔离，同域）
- **Related Commits**: `a534116`（含实例迁移）；规则入 TESTING.md §1/§8 与 AGENTS.md §7/§8/§15
- **Related Evaluation Reports**: 无独立报告（测试期事故）

## 1. Symptom

一次集成测试运行后，真实 Novel 节点全部消失；库中残留 329 孤儿 Person + 577 条 RELATES_TO。

## 2. User-visible / System Impact

- 用户上传的真实小说（Novel + Person + RELATES_TO）被测试清理误删。
- 后续依赖该数据的所有页面/图谱为空；孤儿 Person/边 污染统计与查询。
- 数据丢失无自动恢复流程。

## 3. Trigger

看到以下任一现象，优先怀疑本问题：

- integration test 运行后 Novel 消失
- 测试断言「空列表」后真实数据没了
- 库中出现大量无 Novel 归属的孤儿 Person
- 代码/测试中出现 `MATCH (n:Novel) DELETE n` 或 `MATCH (n) DELETE n`

## 4. Minimal Reproduction

1. 库中已有真实 Novel（非测试 novel_id）。
2. 运行一个集成测试，其清理逻辑为 `MATCH (n:Novel) DELETE n`（用于断言「空列表」）。
3. 测试结束后：真实 Novel 全部被删，Person/边残留。

## 5. Investigation Path

```text
Step 1  git log / git diff 找出最近新增或修改的测试
Step 2  grep -n "DELETE" 测试与脚本，找无 novel_id 范围的 DELETE
Step 3  检查是否绕过 db.delete_novel 直接执行原生查询
Step 4  对照 TESTING.md §1/§8 确认隔离规则是否被违反
Step 5  评估影响范围（孤儿 Person/边数量）并决定是否恢复
```

## 6. Evidence

- 事故现场：329 孤儿 Person + 577 RELATES_TO（无 Novel 归属）。
- 修复 commit `a534116`：测试改为独立 novel_id 自建自清；`test_list_novels_empty` 改为非破坏性结构断言。

## 7. Root Cause

测试为了断言「空列表」执行 `MATCH (n:Novel) DELETE n`。Novel 与 Person/RELATES_TO 是分离的节点/边，只删 Novel 留下孤儿；且该 DELETE 无 novel_id 范围，波及真实数据。

## 8. Why

「数据库初始为空」的假设使测试作者选择全量清理这一捷径；ER 模型（Novel/Person/RELATES_TO 分离）意味着只删 Novel 不会清干净；而实例上又有真实数据——三个因素叠加导致事故。

## 9. Failed Approaches

- 测试内执行全库/全 Novel 的 `DELETE` 作为清理（已证伪：破坏真实数据）。

## 10. Correct Approach

- 删除一律 `db.delete_novel(novel_id)`（按 id 精确；删除前 dry-run 列目标）。
- 每个测试用例创建独立 `novel_id`，结束后只清理自己的。
- 「空列表」断言用非破坏性结构断言（只统计自己 novel_id 的数据）。
- 规则固化进 TESTING.md §1/§8 与 AGENTS.md §7/§8/§15。

## 11. Invariants

- 任何测试/脚本不得执行无 novel_id 范围的 DELETE / DETACH DELETE。
- 测试只操作自己的 novel_id；不依赖「数据库初始为空」。
- 数据删除优先复用 `db.delete_novel(novel_id)`。

## 12. Validation

- 修复后全部集成测试通过且不触碰真实数据；`test_list_novels_empty` 非破坏性断言生效。

## 13. Trade-offs / Limitations

- 测试无法断言「全库为空」，只能断言自己的数据域；共享库中长期存在其他数据是常态。

## 14. Decision

- 测试数据隔离规则入 TESTING.md §1/§8；删除操作强制走 `db.delete_novel`；AGENTS.md §7 明确禁止无范围 DELETE。

## 15. Follow-up

- 无待办。可选增强：评审/静态检查中增加「grep 无范围 DELETE」步骤。

## 16. Do Not Reopen Without Evidence

若再次出现「Novel 消失」：

1. 先 grep 新增测试/脚本中是否出现无 novel_id 范围的 DELETE（代码回退）。
2. 检查 `db.delete_novel` 是否被传了错误 novel_id（输入变化）。
3. 检查连接是否指向共享实例 7474/7687 而非 novel-neo4j（环境变化）。
4. 不要直接改回「空库清理」方案——那是已被证伪的错误做法。
