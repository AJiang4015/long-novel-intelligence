# problem.md — 项目长期问题知识库

> 记录 Bug / 根因 / 解决方案 / 验证 / 工程事故 / 环境问题 / 限制与经验。
> 状态：`resolved`（已解决）/ `investigating`（未完全解决）。
> 维护规则见 `AGENTS.md` §10。不删除历史记录。

---

## A. 工程事故

### A1. 集成测试全库删除 Novel → 孤儿数据事故

- **Status**: `resolved`
- **Problem**: `test_list_novels_empty` 执行 `MATCH (n:Novel) DELETE n`，一次集成测试运行清空全部真实 Novel 节点，留下 329 孤儿 Person + 577 条 RELATES_TO（novel_id 指向不存在的 Novel）。
- **Root Cause**: 测试为断言「空列表」而无条件删除全库 Novel；且只删 Novel、不删 Person/边。
- **Why**: 违反数据隔离——测试不得做无范围 destructive 操作。
- **Solution**: 该测试改为**非破坏性结构断言**（只验证列表结构）；删除操作一律走 `db.delete_novel(novel_id)` 按 id 精确清理。规则写入 `TESTING.md` §1/§8。
- **Validation**: 集成测试全绿；新实例测试后 `novels=0 persons=0`。
- **Trade-offs**: 失去「空列表」精确断言，由 sorted/结构用例覆盖。
- **Git commit**: `a534116`（含独立实例迁移）。

### A2. 共享 Neo4j 与医疗图谱同库风险

- **Status**: `resolved`
- **Problem**: 小说项目连接 VM 上共享 Neo4j（python-project 栈，含约 4.8 万医疗图谱节点：疾病/药品/食物/检查项目/疾病症状/治疗方法/药品商），任何全局操作都可能波及他人数据。
- **Root Cause**: VM `python-project` docker-compose 栈（neo4j:5.26.0）与小说项目共用 7474/7687。
- **Why**: 跨业务共享数据库缺乏隔离。
- **Solution**: 停用 python-project 栈（`docker compose stop` + `docker update --restart=no` ×6）；新建独立 `novel-project` 实例（`novel-neo4j`，端口 7474/7687，卷 `novel_neo4j_data`，密码 12345678）。后端 `.env` 连接不变（`bolt://192.168.127.101:7687`）。
- **Validation**: 新实例空库、Windows 可达、认证 OK、集成测试全绿。
- **Trade-offs**: 旧医疗栈恢复需手动（端口冲突）。
- **Git commit**: `a534116`。

### A3. python-project 容器自启动

- **Status**: `resolved`
- **Problem**: python-project 6 个容器 `restart=always`，Docker 守护进程重启即拉起（无视手动 stop）。
- **Root Cause**: compose 默认/显式 `restart: always`。
- **Solution**: `docker update --restart=no` ×6 容器，全部 `status=exited`。
- **Validation**: 重启策略确认 `restart=no`。
- **Git commit**: VM 操作（无仓库 commit）。

---

## B. Bug

### B1. llm_client 缺失 Authorization 头

- **Status**: `resolved`
- **Problem**: 真实 LLM 调用必 401（保存了 key 但 POST 未带 `Authorization: Bearer`）。
- **Root Cause**: 计划代码缺陷——`_api_key` 未被使用。
- **Solution**: POST 补 `headers={"Authorization": f"Bearer {self._api_key}"}`；加单测锁死。
- **Validation**: `test_extract_chunk_sends_bearer_auth_header`；全量测试绿。
- **Git commit**: `8c25836`。

### B2. ebooklib 0.20 `get_title` 不存在

- **Status**: `resolved`
- **Problem**: `EpubHtml.get_title()` AttributeError（0.20 无该方法）。
- **Root Cause**: ebooklib 0.20 API 变化（title 为实例属性）。
- **Solution**: `getattr(item, "title", "")`。
- **Validation**: epub 解析测试通过。
- **Git commit**: `f2b03c6`。

### B3. Neo4j 属性不支持 map → JSON 序列化

- **Status**: `resolved`
- **Problem**: `chapters`/`evidence` 为 list[dict]，作为属性存储报错。
- **Root Cause**: Neo4j 属性值不允许 map（仅原始类型/数组）。
- **Solution**: `json.dumps` 存储、读取 `json.loads` 还原（upsert_novel/get_novel/upsert_graph/get_subgraph）。
- **Validation**: 集成测试通过。
- **Git commit**: `dcf6023` 系。

### B4. `get_subgraph` 结果在会话外迭代 → ResultConsumedError

- **Status**: `resolved`
- **Problem**: neo4j driver 会话关闭后迭代未消费的 Result 报 `ResultConsumedError`。
- **Root Cause**: `records = session.run(...)` 在 `with session` 外使用。
- **Solution**: `records = list(session.run(...))`（会话内物化）。
- **Validation**: 集成测试通过。
- **Git commit**: `dcf6023` 系。

### B5. 计划/评审发现的代码缺陷（一轮修复）

- **Status**: `resolved`
- **Problem 清单**: ① `api.ts` `handle(fetch(...))` 传 Promise<Response>；② `characters.py` 参数默认值顺序 SyntaxError；③ 计划缺 `GET /api/novels/{id}` 端点代码；④ `merge_extractions` 测试与实现签名不一致（1 参 vs 2 参）；⑤ `judge_aliases` 计划片段与其自身重试测试矛盾。
- **Root Cause**: 计划代码缺陷/自相矛盾，由 subagent 评审与测试拦截。
- **Solution**: 最小修正（见各 commit），并以测试锁死。
- **Git commit**: `d562039` 系 / `f3baf2a` / `331c6b8` 等。

### B6. extractor 吞掉 4xx 具体状态码

- **Status**: `resolved`
- **Problem**: `unexpected:LLMError` 无法区分 400/401/403，故障定位困难。
- **Root Cause**: `extract_one` 把 `LLMError` 作为通用异常捕获，丢失状态码。
- **Solution**: `llm_client` 增加诊断日志：`[llm] stage=extract|judge status=<code> body=<摘要>`（不含 API key）。
- **Validation**: 真实评估日志捕获到 `code=Arrearage`/`code=limit_requests`，定位成功。
- **Git commit**: `36e8019`。

---

## C. 环境问题

### C1. 沙箱 pip 不可用 → 手动解包依赖

- **Status**: `resolved`（环境特定）
- **Problem**: pip 在沙箱内无法安装（wheel 解包 Permission denied；venv ensurepip 失败）。
- **Root Cause**: 沙箱拦截长进程创建目录后的读写/删除。
- **Solution**: 依赖手动解包到 `backend/.deps`，`conftest.py` 注入 `sys.path`；运行命令带 `PYTHONPATH`。
- **Validation**: 全量测试绿。
- **Git commit**: `3267755`（conftest/pyproject 适配）。

### C2. pytest tmp_path/basetemp 被沙箱锁定

- **Status**: `resolved`（环境特定）
- **Problem**: `tmp_path` fixture 与 basetemp 目录被沙箱锁定，测试 ERROR。
- **Solution**: ① `epub_factory.build_epub` 改用 `BytesIO`（不落盘、无 tmp_path）；② pytest 禁缓存（`-p no:cacheprovider`）；③ conftest 每次运行唯一 basetemp。
- **Validation**: 全量测试绿。
- **Git commit**: `3267755` 系。

### C3. vite build `spawn EPERM`（exec "net use"）

- **Status**: `resolved`（环境特定，补丁易失效）
- **Problem**: vite 8 加载配置时 `exec("net use")` 被沙箱拒（EPERM）。
- **Solution**: node_modules 本地 try/catch 补丁（**不提交**；重装 npm 后需重打）。
- **Validation**: `npm run build` 通过。
- **Git commit**: 无（本地补丁）。

### C4. 百炼账号欠费 Arrearage（非代码）

- **Status**: `resolved`（账号层，非代码可修）
- **Problem**: 全部 LLM 调用返回 400 `code=Arrearage`；欠费充值后**又复现**（探测 200 → 运行期再次欠费）。
- **Root Cause**: 阿里云百炼账号余额/欠费状态（与模型名无关，跨模型均 400）。
- **Solution**: 用户充值；增加诊断日志以便区分；并发 1 降低限流。
- **Validation**: 充值后探测 200，完整 ingest 0 失败。
- **Trade-offs**: 评估依赖账号状态，外部阻塞。
- **Git commit**: `36e8019`（日志）。

---

## D. 限制与经验

### D1. 零共享字称谓对未合并（二老↔傩送、天保↔大老）

- **Status**: `investigating`
- **Problem**: 《边城》真实评估中 `二老`/`傩送`、`天保`/`大老` 各自独立 canonical（零共享字符：{二,老} vs {傩,送}）。
- **Root Cause**: 字符重叠/子串召回对零共享字无信号；合并依赖「同 chunk 共现 + LLM 判定为同一人」同时成立；首现规则下先出现者（二老/大老）定 canonical 后缓存命中不再复判。
- **Solution（未定，未改算法）**: mention hygiene / judge 判定加强 / 轻量共现或向量召回（需另行评估）。
- **Validation**: `docs/evaluation/2026-08-21-biancheng-er-stability.md`（novel `3d782d98`）。
- **Git commit**: `685d019`（评估报告）。

### D2. `傩送二老` 垃圾别名（mention hygiene）

- **Status**: `investigating`
- **Problem**: 提取 LLM 输出畸形人物名（如「傩送二老」），被 ER 吸收为别名或独立 canonical。
- **Root Cause**: judge 契约只有 `resolves_to ∈ 候选 | null`，无「无效 mention 丢弃」选项。
- **Solution**: 预留 drop 能力（schemas/judge prompt 扩展），下一步单独处理。
- **Git commit**: 无（未改）。

### D3. 全部 chunk 失败时 job 状态应为 failed

- **Status**: `investigating`（观察到的 spec 语义缺口，未修）
- **Problem**: 27/27 chunk 失败时 job 仍为 `completed_with_errors`；spec §5.1 定义「全部 chunk 失败 → failed」。
- **Root Cause**: `_run_ingest` 只按 `failed_blocks` 非空判 `completed_with_errors`；`failed` 仅在异常路径设置。
- **Solution**: 需在 `_run_ingest` 终态判定补「全部失败 → failed」（代码变更，未授权未实施）。

### D4. 工具超时杀轮询脚本 → job_id 丢失

- **Status**: 经验
- **Problem**: 轮询脚本被工具 10 分钟超时终止，Python stdout 缓冲导致已打印的 novel_id/job_id 丢失。
- **经验**: 长任务脚本用 `python -u`（无缓冲）+ 后台任务方式运行；后端 ingest 是后台任务，脚本被杀不影响后端继续。
- **Git commit**: 无。

### D5. ER 计划测试与实现语义互斥（流程教训）

- **Status**: `resolved`
- **Problem**: 计划中 3 个测试断言与「known 整本持续（含 alias）」语义互斥（同 chunk 再判 vs 缓存命中）。
- **Solution**: 以 spec 语义为准修订测试（不削弱行为断言），重跑全绿。
- **Git commit**: `f3baf2a`。

### D6. 同 chunk 共现召回顺序敏感

- **Status**: `resolved`
- **Problem**: 未知 mention 在已知名之前出现时丢失共现候选（top-5 被字符重合占满）。
- **Root Cause**: `confirmed` 从空集随处理顺序累积。
- **Solution**: chunk 预扫描——处理前把本 chunk 中已知名预置进 `confirmed`。
- **Validation**: 新增正反序一致性测试；51 单元全绿。
- **Git commit**: `c850bda`。
