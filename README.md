# 长篇小说知识图谱分析系统 V0.1

上传 EPUB 小说 → 选择人物 → 查看该人物的 1 跳人物关系网络。

## 启动

1. `cp .env.example .env`，填写 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`；如修改了 Neo4j 密码需同步 `.env`
2. `docker compose up -d neo4j`
3. 后端：`cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload --port 8000`
4. 前端：`cd frontend && npm install && npm run dev`（访问 http://localhost:5173）

## 测试

- 单元测试（无需 Neo4j / 真实 LLM）：`cd backend && pytest`
- 集成测试（需 Neo4j 运行中）：`cd backend && pytest -m integration`

## V0.1 已知限制

> **Job state is process-local in V0.1 and will be replaced by a persistent task store in later versions.**

- 人物不做别名归并：LLM 输出的不同写法视为不同 Person
- 关系为有向边，方向仅表示抽取时的主体 → 客体
- weight = 确认该关系的不同 chunk 数；confidence = 各确认 chunk confidence 的算术平均
