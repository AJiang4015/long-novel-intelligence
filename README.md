# 长篇小说知识图谱分析系统 V0.1

上传 EPUB 小说 → 选择人物 → 查看该人物的 1 跳人物关系网络。

## 启动

1. `cp .env.example .env`，填写 `BAILIAN_API_KEY`（阿里百炼 API Key）；如修改了 Neo4j 密码需同步 `.env`
   - LLM 使用阿里百炼：`BAILIAN_URL`（OpenAI 兼容地址，默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`）、`BAILIAN_MODEL`（默认 `qwen3.7-max-2026-05-17`）
2. 启动 Neo4j：
   - **远程部署（本项目实际使用）**：VM 192.168.127.101 上 `/root/novel-project/docker-compose.yml` 的独立 `novel-neo4j` 实例（neo4j:5.26.0，端口 7474/7687，密码 `12345678`，数据卷 `novel_neo4j_data`，与任何其他项目完全隔离）
   - 本机 Docker 备用：`docker compose up -d neo4j`（仓库 compose 与远程实例配置一致）
   - `.env` 的 `NEO4J_URI` 指向实际实例：`bolt://192.168.127.101:7687`（本机部署则 `bolt://localhost:7687`）
3. 后端：`cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload --port 8000`
   - 若本机 pip 不可用（如沙箱环境），依赖可手动解包到 `backend/.deps`，运行前设置 `$env:PYTHONPATH='backend\.deps'`
4. 前端：`cd frontend && npm install && npm run dev`（访问 http://localhost:5173）

## 测试

- 单元测试（无需 Neo4j / 真实 LLM）：`cd backend && pytest`
- 集成测试（需 Neo4j 运行中）：`cd backend && pytest -m integration`

## API

| 端点 | 说明 |
|---|---|
| `POST /api/novels` | 上传 .epub → `{novel_id, job_id}` |
| `GET /api/jobs/{job_id}` | 任务状态与进度（pending/running/completed/completed_with_errors/failed） |
| `GET /api/novels/{novel_id}` | 小说元信息（标题、章节、统计） |
| `GET /api/novels/{novel_id}/characters?q=` | 模糊搜索人物候选 |
| `GET /api/characters/{character_id}/graph` | 1 跳人物关系子图 |
| `GET /api/health` | 健康检查（含 Neo4j 连通性） |

## 已知限制

> **Job state is process-local（V0.1 决策）and will be replaced by a persistent task store in later versions.**

- 人物消歧质量取决于抽取与判定（LLM 非确定性）：真实评估结论见 `docs/evaluation/`，已知问题见 `PROBLEM.md` / `docs/problems/`
- 关系为有向边，方向仅表示抽取时的主体 → 客体
- weight = 确认该关系的不同 chunk 数；confidence = 各确认 chunk confidence 的算术平均

## 文档

| 文档 | 内容 |
|---|---|
| `AGENTS.md` | Agent 必须遵守的硬规则（宪法） |
| `PROCESS.md` | 项目流程 / 实验纪律 / 验收顺序 |
| `DECISIONS.md` | 已做出的架构 / 工程决策 |
| `ARCHITECTURE.md` | 系统结构与数据流 |
| `PROBLEM.md` | 问题地图 + 诊断路由（`docs/problems/` 为完整记录） |
| `TESTING.md` | 测试与真实评估规范 |
| `DESIGN.md` | UI/UX Design System |
| `backend/app/*/*_LAYER.md` | 各层契约与边界 |

> 后端分层：`api`（HTTP 编排）/ `db`（Neo4j）/ `models`（任务状态机）/ `pipeline`（抽取·消歧·合并·观测）/ `schemas`（契约）。
