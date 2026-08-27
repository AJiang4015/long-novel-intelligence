# DB_LAYER.md — db 层契约与边界

> 定位：**Layer Contract / Layer Boundary**（本层负责什么、不能负责什么），不是代码使用说明。
> 全局架构见 `../../../ARCHITECTURE.md`；数据安全红线见 `../../../AGENTS.md` §2。

## 1. Responsibility

Neo4j 访问封装（`Neo4jDB`）：

- 按 novel_id 隔离的读写（人物查询 novel_id + character_id 双层隔离）
- 约束管理（`ensure_constraints`：`person_id` / `(novel_id, name)` 唯一）
- 单事务写入（`upsert_graph`：C_keep upsert → RELATES_TO upsert → C_drop DETACH DELETE）
- 精确删除（`delete_novel(novel_id)`）
- 数据模型边界：只负责 `Novel` / `Person` / `RELATES_TO`

## 2. Input contract

- `novel_id` + 领域对象：`MergedGraph`（persons / relationships）、`merge_map`（C_drop → C_keep）、chapters、title
- 查询参数（novel_id / character_id / q）

## 3. Output contract

- 持久化状态（Novel / Person / RELATES_TO 节点与边）
- 查询结果（人物候选、关系图、统计）

## 4. Decision ownership

- 写库事务边界（单事务，任一步异常 → 整体 rollback，无半合并状态）
- 约束定义与创建
- 删除语义（按 novel_id 精确；删除前 dry-run 列目标）
- 序列化策略（Neo4j 属性仅原始类型/数组；list[dict] JSON 序列化）

## 5. Allowed dependencies

- neo4j driver（唯一外部依赖）

## 6. Forbidden dependencies

- 不依赖 pipeline / models / api / schemas（无业务类型耦合；输入为通用对象）
- 不做业务决策（canonical 选择、合并判断、role 判定、mention 分类）
- 禁止无范围 destructive query（`MATCH (n) DELETE n` / `DETACH DELETE` / `MATCH (n:Novel) DELETE n`）
- 禁止触碰其他标签/实例/业务数据（P02 教训）

## 7. Invariants

- 所有查询/写入按 novel_id 隔离；跨 novel_id 操作被禁止
- 属性仅原始类型（chapters JSON 序列化存储）
- `upsert_graph` 单事务：失败回滚，不产生半合并状态
- `delete_novel` 是唯一合法删除入口（测试/修复不得绕过）

## 8. Failure ownership

- 连接错误 / ping 失败 → 上层（api）映射 503
- `ResultConsumedError` 等驱动坑 → 封装层修复（P14 经验，不扩散到调用方）
- 事务异常 → rollback 并向上抛（调用方记录 job 失败）

## 9. Testing expectations

- integration：真实 Neo4j（novel-neo4j），独立 novel_id 自建自清（fixture teardown 调 `delete_novel`）
- 不得清空数据库；不依赖「初始为空」（`../../../TESTING.md` §1）
- 删除操作前 dry-run 列目标（`../../../TESTING.md` §7）

## 10. Typical changes allowed here

- 查询封装 / 新查询方法（按 novel_id 隔离）
- 约束调整 / 事务写法优化
- 未来持久化迁移（job store 持久化在 models 层，与 db 层无关）

## 11. Changes that must be implemented elsewhere

- canonical merge 判定 / mention 分类 / role gate：→ `pipeline`（`../pipeline/PIPELINE_LAYER.md`）
- HTTP 契约：→ `api`（`../api/API_LAYER.md`）
- 新增标签 / 关系类型：先走 `../../../DECISIONS.md` 与 `../../../PROCESS.md` 立项（D-3 边界）
