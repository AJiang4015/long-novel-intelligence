# TESTING.md — Long-Novel-Intelligence 测试与真实验收规范

> 本文是项目**统一测试规范**与**真实 LLM 评估规范**的唯一事实来源。
> 任何测试/评估的修改都必须遵守本文约束；冲突时以本文为准。
> 关联：`docs/superpowers/specs/2026-08-21-entity-resolution-design.md`（实体消歧语义）。

## 0. 环境基线（当前）

| 项 | 值 |
|---|---|
| Neo4j 实例 | 独立容器 `novel-neo4j`（VM 192.168.127.101，`bolt://192.168.127.101:7687`，neo4j/12345678，5.26.0 Community，卷 `novel_neo4j_data`） |
| 其他项目数据 | **共享 VM 上另有 python-project（医疗图谱）**——本规范严禁任何操作触碰其标签/数据 |
| LLM | 阿里百炼 OpenAI 兼容：`BAILIAN_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、`BAILIAN_MODEL=qwen3.7-max-2026-05-17`（可被 `.env` 覆盖） |
| 切块 | `CHUNK_SIZE=4000`、`CHUNK_OVERLAP=400`、`LLM_CONCURRENCY=4`（来自 `backend/.env`，可覆盖） |

## 1. 数据隔离（铁律）

- **自动化测试只能操作自己创建的 novel_id**（`uuid4` 或测试前缀如 `list-`）
- **任何测试禁止清空全库**：禁止 `MATCH (n:Novel) DELETE n`、`DETACH DELETE` 无范围执行
- 清理必须按 novel_id 精确执行（`Neo4jDB.delete_novel(novel_id)`，作用域 = 该 novel 的 Person/RELATES_TO/Novel）
- **禁止触碰其他标签**（如医疗图谱的 疾病/药品/食物/…）或其他业务数据
- 历史教训：`test_list_novels_empty` 曾执行 `MATCH (n:Novel) DELETE n`，一次集成测试运行清空了全部真实 Novel 节点、留下 329 孤儿 Person——**此类写法在本项目被永久禁止**（现该测试已改为非破坏性结构断言）

## 2. 自动化测试

> 纯文档变更（不涉及代码 / 测试 / prompt / 配置 / 数据）可跳过测试执行，见 `AGENTS.md` §5 docs-only 例外。

### Unit（`cd backend && python -m pytest`）

- **Mock LLM**：`llm_client` 通过注入 `http_client`（`FakeHttpClient`）模拟响应；`resolver` 通过注入 `judge` 可调用对象
- **deterministic**：不允许依赖真实 LLM/网络/时间
- 不依赖外部网络、不连接 Neo4j、不读 `.env` 之外的配置
- **文件落盘**：P12 沙箱限制——pytest `tmp_path`（mode=0o700）目录会被沙箱锁定，测试**默认不落盘**（BytesIO）；
  必须落盘的用例（如 `test_lineage.py` 的 recorder flush / diagnose JSONL）写入工作区 `../.tmp/lineage-tests/`
  并在 teardown 清理（fixture `ws_tmp`；`.tmp/` 已 gitignore）
- 现有文件：`tests/unit/{test_config,test_chunker,test_merger,test_llm_client,test_job_store,test_resolver,test_hygiene,test_resolver_context,test_resolver_descriptive,test_role_policy,test_sections,test_merge,test_lineage}.py`
- Resolver 语义锁死用例（`test_resolver.py`）不可削弱，见 §8

### Integration（`cd backend && python -m pytest -m integration`）

- 使用**独立 novel_id**（`uuid4`）；测试前创建数据（`db.upsert_novel` / 上传接口）、测试后**按 novel_id 精确清理**（fixture teardown 调 `delete_novel`）
- **不得清空数据库**（见 §1）
- 需要 Neo4j 运行中（`novel-neo4j`）；`db` fixture 连不上时 `pytest.skip`
- 现有文件：`tests/integration/test_api_neo4j.py`

## 3. Real LLM Evaluation（与 pytest 分离）

真实 BAILIAN/Qwen 评估**不得混入 pytest**（pytest 永远全 mock）。执行方式为独立脚本/手动流程。

每次真实评估必须：

- 使用**全新的 novel_id**（新上传，绝不复用旧 Novel）
- 不在已有 Novel 上增量测试
- 记录（见 §6 Environment Baseline）
- 记录结果（见 §9 Reporting）
- **非确定性声明**：真实 LLM 输出（judge 判定、提取结果）存在非确定性（P06）——单次运行结果不代表结论；结论需多次运行取趋势，报告注明运行次数与波动（规则见 `AGENTS.md` §3，流程见 `PROCESS.md` §2）

## 4. Evaluation Baseline（《边城》）

固定测试人物：

| 组 | 人物 | 期望 |
|---|---|---|
| 正向 1（零共享字，靠同 chunk 共现） | `傩送` / `二老` | 归并为同一 canonical，aliases 含 二老 |
| 正向 2（零共享字） | `天保` / `大老` | 归并为同一 canonical |
| 正向 3（字符重合） | `老船夫` / `爷爷` / `老人` | 归并为同一 canonical |
| 负向（明确不同人物） | `傩送` vs `杨马兵`（或 `天保` vs `傩送`） | **必须不合并** |

> **验收边界（D-19，2026-08-28）**：**单次、低显著性 mention 不要求稳定覆盖**。`老二`（全文仅 1 次出现的反说昵称，`傩送` 的别名变体）从正向 1 组的**必须满足项**中移除，降为**观察项**（checkset `A7`，OBSERVATION 不判败）——其漏提属 extraction coverage 模型能力边界（P021，Task A 已归因），不是 correctness FAIL。核心 gate 由 傩送/二老 归并承载（checkset `A1`）。

验证项：

- canonical 数量（期望：上述正向组各自 1 个 canonical）
- `aliases` 内容（不含 canonical 自身、去重、保序）
- `mention_count`（= canonical+别名在 characters 字段的 distinct chunk 数）
- `chapters`（出现章节列表）
- relationship 数量
- **搜索 alias 只返回对应 canonical**：`GET /api/novels/{novel_id}/characters?q=二老` → 命中且 name 为「傩送」；不允许同时返回两个「人物」

> **P20 可执行化**：本节期望已编码为 checkset（`backend/tools/eval_framework/checks.py` 的 `CHECKSET_V2`，检查 id A1-A7 对应本节各组；§9.1 指标编码为 B-G 组；v2 = D-19 验收边界修订）。**数据库验收的正式执行入口见 §5**（由 eval_framework 取代手工 Cypher）；本节仍是检查期望的事实来源，修改期望须走 P20 checkset 版本管理（P020 Spec §4.2 / DECISIONS D-19）。

## 5. 数据库验收（禁止只看前端）

> **正式执行入口（P20）**：数据库验收由 `backend/tools/eval_framework/` 执行——runner 采集 Neo4j 稳定键快照（`_graph_snapshot`）+ `checks.evaluate_checkset(CHECKSET_V2)` 自动判定（检查 id A1-A7 + B-G，判定分类 PASS/FAIL/OBSERVATION/INCONCLUSIVE/SKIP），报告由 `report.py` 按 §9 模板自动生成。**手工 Cypher 不再作为验收主流程**，仅保留为人工复核/深挖手段（用法见 `backend/tools/eval_framework/README.md`）。单次真实评估不构成结论（§3 非确定性声明），需多次运行取趋势或与基线比较。

禁止只通过前端关系图判断 Entity Resolution 成败。必须**直接查询 Neo4j** 并保存关键结果（以下查询与 runner 的 `_graph_snapshot` 等价，供人工复核/深挖使用）：

```cypher
MATCH (p:Person) WHERE p.novel_id = $novel_id
RETURN p.name, p.aliases, p.mention_count, p.chapters
ORDER BY p.mention_count DESC;

MATCH (:Person)-[r:RELATES_TO]->(:Person) WHERE r.novel_id = $novel_id
RETURN count(r) AS relationships;

MATCH (p:Person) WHERE p.novel_id = $novel_id
  AND (p.name CONTAINS $q OR ANY(a IN p.aliases WHERE a CONTAINS $q))
RETURN p.name, p.aliases;
```

查询结果保存到评估报告（§9）。

## 6. Environment Baseline（真实测试前必记）

| 项 | 来源 |
|---|---|
| Git commit | `git rev-parse HEAD` |
| Neo4j version | `dbms.components()` 或容器镜像 tag |
| LLM model | `backend/.env` 的 `BAILIAN_MODEL` |
| chunk size | `CHUNK_SIZE` |
| overlap | `CHUNK_OVERLAP` |
| concurrency | `LLM_CONCURRENCY` |
| novel_id | 本次上传生成的 id |
| 后端代码状态 | 是否本地未提交修改（`git status --porcelain`） |

> **P20**：本节字段是 eval_framework 的事实来源——runner `_collect_env()` 逐项采集并写入 run result.json 的 `env`，缺失 → refuse；`compare_identity`（Spec §5.2）的兼容性判定与本节同源（model / chunk / overlap / 版本），用法见 `backend/tools/eval_framework/README.md`。

## 7. Cleanup

- **自动化测试**：只删除自身创建的 novel_id（fixture teardown）；禁止任何全局清理
- **Real evaluation**：默认**不删除结果**（保留以复现/审计）
- 需要删除时：必须**显式指定 novel_id**，禁止 `DELETE` 通配
- 任何 cleanup 执行前必须先 **dry-run / 列出目标**（如 `MATCH (p:Person) WHERE p.novel_id IN [...] RETURN count(p)`），确认后再执行
- 删除单个 novel：`Neo4jDB.delete_novel(novel_id)`（按 id 精确）

## 8. Regression（Resolver 每次修改后必测）

每次修改 `resolver.py` / 相关召回/判定逻辑后，至少重新验证以下行为（`tests/unit/test_resolver.py` 已有锁死用例，**不得削弱断言**）：

- [ ] alias cache（已确认别名缓存命中，不再触发 judge）
- [ ] canonical first appearance（首次出现定主名，不重选）
- [ ] same-chunk co-occurrence（零共享字同 chunk 共现召回）
- [ ] reverse order co-occurrence（未知在前也能召回已知名——chunk 预扫描）
- [ ] null resolution（判 null → 新 canonical，不二轮）
- [ ] resolution failure continuation（判定失败 → 独立 canonical + failed 记录 + 后续 chunk 继续）
- [ ] mention_count distinct chunk 语义（同 chunk 多次出现只 +1）

回归命令：`cd backend && python -m pytest tests/unit/test_resolver.py -v && python -m pytest && python -m pytest -m integration`

## 9. Reporting（真实评估报告模板）

每次真实评估产出报告（建议存 `docs/evaluation/YYYY-MM-DD-<tag>.md`），必须包含：

> **评估报告声明（强制）**：报告标题与顶部必须注明「本报告是 XX 版本的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record」。防止「P17 = PARTIAL」等结论被直接当成改代码指令。

> **P20**：`backend/tools/eval_framework/report.py` 自动生成 §9 模板报告（run / baseline / compare 三种），**强制声明语句自动输出**；人工撰写/补充的报告仍须遵守本模板与声明。模板与验收指标（§9.1）本身不变——它们是 checkset 的期望来源（`checks.py` `CHECKSET_V2`，修改期望须 bump checkset_version，见 D-19）。

```markdown
# ER Evaluation Report — <小说名>（<YYYY-MM-DD>）

## Symptom / Goal
本次评估目标（如：验证 二老↔傩送 零共享字别名在共现召回下是否合并）

## Environment
- Git commit: <hash>
- Neo4j: <version> <edition>（novel-neo4j）
- Model: <model>  |  chunk_size / overlap / concurrency: <4000 / 400 / 4>
- Novel ID: <novel_id>

## Before / After Statistics
- 上传前：novels=… persons=… relationships=…
- 上传后：persons=… relationships=… （按 §5 查询）

## Canonical Examples
| canonical | aliases | mention_count | chapters |

## Alias Examples
（含负向：确认 傩送/杨马兵 未合并）

## Failure Cases
（未合并/误合并/异常，附 failed_blocks 或证据）

## Known Limitations
（如：零共享字且不同 chunk 时仍需候选+LLM；判定概率性；mention hygiene 未做）
```

### 9.1 版本化验收指标与归因纪律

> 指标随版本演进，标注版本号；归因纪律的权威位置在各 Problem Record（此处为速查）。

**V0.2.5 起验收指标（真实评估必须采集）**：

- 非正文 canonical 数量（期望 0）
- provisional → promoted / provisional → dropped 计数
- DESCRIPTIVE resolved / unresolved / canonical 数量
- ch5b 一族（大儿子/长子/次子/第二个儿子/天保/傩送）canonical 收敛情况
- P18 观察：正文角色称谓吸收（顺顺 aliases 含 父亲/爸爸/爹爹 类）——正吸收 vs 跨人物错吸

**归因纪律（V0.2.5 起）**：

- `顺顺→父亲` 类正文吸收仍存在 ≠ P16-a/P17 失败（P18 独立问题，角色称谓吸收语义可能正确；先做 aliases 可解释性核对）
- ch5b 一族未收敛 ≠ B1 机制失败——先查 extraction category（D5 缺口：category=None → PERSON fallback）再查 judge（P06）
- merge 整体 failed_pairs ≠ 算法失败——batch merge judge 一次异常即全记 failed（INCONCLUSIVE）

## 附：常用命令速查

```powershell
# 单元（全 mock，无网络/Neo4j）
cd backend; python -m pytest

# 集成（需 novel-neo4j 运行中；默认只跑 unit，显式 -m integration）
cd backend; python -m pytest -m integration

# 单项
cd backend; python -m pytest tests/unit/test_resolver.py -v

# 真实评估前环境基线
git rev-parse HEAD; docker exec novel-neo4j 环境探针（或 dbms.components）
```
