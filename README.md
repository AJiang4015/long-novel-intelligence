# 长篇小说人物关系知识图谱分析系统

> 基于 **LLM + Entity Resolution + Neo4j** 的长篇小说人物关系分析系统：上传 EPUB，自动抽取人物与关系，把同一个人物的不同称谓合并为统一实体，构建可查询、可可视化的人物关系图谱，并附一套可重复执行的 regression evaluation 框架。

---

## 核心能力（均为已实现能力）

- **EPUB 小说解析**：章节结构解析 + 正文/版权/题记/推广分类（非正文不污染实体）
- **chunk pipeline**：按 `CHUNK_SIZE / OVERLAP` 确定性切块，chunk_id 全局递增
- **LLM extraction**：每 chunk 抽取人物 + 关系 + 类别标注（阿里百炼 / 任意 OpenAI 兼容 endpoint）
- **Entity Resolution**：candidate recall → LLM judge → admission → registration 的整本消歧（canonical 首现锁定，不重选）
- **alias merge**：零共享字别名（`天保 ↔ 大老`、`傩送 ↔ 二老`）跨 chunk 合并为统一 canonical
- **角色称谓准入控制**：`X的Y` qualified / 裸称谓 bare 的证据门槛（≥2 独立证据 → confirmed）
- **Neo4j 图谱**：`Novel / Person / RELATES_TO` 三结构，novel_id 双层隔离，单事务写入
- **React 可视化**：上传 → 后台分析 → 人物搜索 → SVG 关系图 → 关系证据（原文片段）展示
- **checkpoint / resume**：中断后重传同一文件自动续跑，已完成阶段**零重复 LLM 调用**（幂等）
- **evaluation framework**：23→24 条声明式检查（checkset v2）+ 真实 LLM 基线 + stable/variance 经验分类 + baseline validity

## 系统架构

```text
┌─ Frontend（React + Vite + TypeScript）────────────────────────────┐
│ App 阶段机（上传→轮询 job→图展示）；GraphCanvas 自绘 SVG 关系图      │
└──────────────┬────────────────────────────────────────────────────┘
               │ REST（/api/...）
┌─ Backend（FastAPI，单进程）───────────────────────────────────────┐
│ api/novels.py  _run_ingest（BackgroundTasks 后台 job）              │
│   EPUB → sections → chunker → extractor(LLM) → hygiene            │
│       → resolver(recall→judge→admission→registration) → merger    │
│       → db/neo4j（最终图单事务）                                    │
│ checkpoint/（durable recovery state，P19）│ models/job（进程内句柄） │
│ tools/eval_framework（regression evaluation，P20）                 │
└──────────────┬────────────────────────────────────────────────────┘
               │ bolt://
        Neo4j 5.26（独立容器，仅 Novel/Person/RELATES_TO）
```

**ingest pipeline 流程图**：

```text
EPUB ─→ 章节分类 ─→ 切块 ─→ LLM 抽取（人物+关系+类别）
  ─→ 确定性硬过滤（集合/泛指词）─→ 消歧（召回候选 → judge → 准入 → 注册）
  ─→ 跨 chunk 合并（bridge evidence + merge judge）─→ Neo4j 写库 ─→ API/前端
```

## 技术栈

| 层 | 技术 |
|---|---|
| Backend | FastAPI · Python 3.13 · Neo4j 5.26（Driver）· 阿里百炼 LLM API（OpenAI 兼容） |
| Frontend | React · TypeScript · Vite · 自绘 SVG GraphCanvas |
| Infrastructure | 文件 checkpoint（resume/幂等）· lineage 观测（全层事件）· evaluation framework（checkset + baseline） |

## Demo 流程

```text
上传 EPUB（.epub ≤50MB）
  → 后台分析（前端轮询 job 进度；失败可续跑）
  → 搜索人物（按名/别名模糊搜索）
  → 查看人物 1 跳关系图（SVG）
  → 点击关系边查看证据（原文 chunk + 章节定位）
```

## 项目亮点（面试重点）

1. **Entity Resolution 而非简单 NER**：同一个人物的姓名/别名/角色称谓在整本书中跨 chunk 归并为单一 canonical；canonical 首现锁定保证确定性，judge 判定 + evidence 门控收敛精度。
2. **lineage 可观测**：extraction → recall → judge → admission → registration → merge 全层事件旁路记录（默认关零开销），任何质量失败可**归因到具体决策层**，不凭经验改代码。
3. **checkpoint / resume**：内容/配置/输入三层指纹 + manifest 两态；中断重传同文件自动续跑，已完成阶段零重复 LLM 调用；幂等重传不浪费 token。
4. **evaluation framework**：真实 LLM 基线 + 经验分类（stable/variance 与 correctness **解耦**）+ baseline validity——**稳定失败不会被冻结为"正常基线"**（`INVALID_NOT_REGRESSION_SAFE` 如实暴露质量问题）。
5. **failure handling**：LLM 限流/超时/形状不合规分类处理、重试语义、checkpoint 写失败降级（不浪费已完成 LLM 工作）、评估侧失败 chunk 自动降级（G4）。

## Known Limitations（诚实清单）

- **extraction coverage 模型边界**：部分角色称谓/低显著性 mention（如 `爹爹`、`老二`）在 flash 类模型下存在漏提（有 lineage 证据，归因为 extraction 层，见 `docs/problems/P017`）；产品验收边界：单次低显著性 mention 不要求稳定覆盖（D-19）。
- **当前 baseline = `INVALID_NOT_REGRESSION_SAFE`**：checkset `C3`（爹爹 ∈ 顺顺.aliases）为稳定失败——框架如实报告该质量问题并**禁止**将其冻结为正常回归基线；这不是缺陷，而是评估框架设计的诚实输出。
- **单次运行成本**：一次《边城》分析约 10-15 分钟真实 LLM 调用（judge 阶段串行为耗时瓶颈），token 成本与模型档位相关。
- **评估语料范围**：质量基线与检查集基于《边城》单语料验证；词表/章节分类/检查期望均为项目级规则，换语料需重新评估（见 D-7/D-16/D-19）。
- **关系语义**：关系为有向边，方向表示抽取时主体 → 客体；`weight` = 确认该关系的不同 chunk 数。

## 本地运行

**环境要求**：Python 3.13+ · Node 18+ · Docker（Neo4j）· 阿里百炼 API Key（或任意 OpenAI 兼容 endpoint）

```bash
# 1. Neo4j（本地开发默认 neo4j/12345678，可用 NEO4J_AUTH 覆盖）
docker compose up -d

# 2. 配置（.env 已被 gitignore）
cp backend/.env.example backend/.env
#    编辑 backend/.env：填写 BAILIAN_API_KEY（必填）、按需改 NEO4J_URI/模型

# 3. 后端
cd backend && pip install -e ".[dev]"
uvicorn app.main:app --port 8000

# 4. 前端（访问 http://localhost:5173）
cd frontend && npm install && npm run dev
```

**测试**：

```bash
cd backend
pytest                  # unit（全 mock，无网络/Neo4j）
pytest -m integration   # integration（需 Neo4j 运行中）
```

**真实评估（可选）**：

```bash
cd backend
python -m backend.tools.eval_framework.runner --dry-run    # 前置校验
python -m backend.tools.eval_framework.runner --smoke      # mock LLM 自检
python -m backend.tools.eval_framework.runner --runs 1     # 1 次真实 ingest 评估
```

> 语料：`books/` 已被 gitignore；放入《边城》（沈从文，公版）EPUB 可复现内置基线（checkset 钉死其 content_hash，语料变化会显式 REFUSE）。评估框架用法见 `backend/tools/eval_framework/README.md`。

## 项目演进

```text
V0.2.x  核心 ER 链路成型（消歧/合并/准入）
P16-a   非正文污染治理 → 已解决并验证
P16-b   角色称谓准入（role gate）→ 机制验证，冻结
P17     描述性碎片化修复（deferred / unresolved 不注册）
P19     checkpoint / resume（可恢复、幂等、零重复调用）
P20     evaluation framework（checkset v2 + 真实基线 + validity）
2026-08 CODE FREEZE（最后一笔：merge_judge payload 修复 MERGE_EVIDENCE_CAP=5）
```

内部工程文档（问题记录/流程/层契约）随仓库公开，见 `docs/`。

## API

| 端点 | 说明 |
|---|---|
| `POST /api/novels` | 上传 .epub → `{novel_id, job_id}`（同文件重传自动续跑） |
| `GET /api/jobs/{job_id}` | 任务状态与进度 |
| `GET /api/novels/{novel_id}` | 小说元信息（标题/章节/统计） |
| `GET /api/novels/{novel_id}/characters?q=` | 人物模糊搜索 |
| `GET /api/characters/{character_id}/graph` | 人物 1 跳关系子图 |
| `GET /api/health` | 健康检查（含 Neo4j 连通性） |

## 文档

| 文档 | 内容 |
|---|---|
| `docs/ARCHITECTURE.md` | 系统架构与依赖方向（即 `ARCHITECTURE.md`） |
| `docs/DECISIONS.md` | 架构/工程决策记录（D-1..D-19） |
| `docs/TESTING.md` | 测试与真实评估规范 |
| `docs/TECHNICAL_MAP.md` | 项目技术知识地图（模块/数据结构/面试要点） |
| `docs/ROADMAP.md` | 项目最终化路线图 |
