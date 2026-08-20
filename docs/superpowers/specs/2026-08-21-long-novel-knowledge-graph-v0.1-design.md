# 长篇小说知识图谱分析系统 V0.1 设计文档

- 日期：2026-08-21
- 版本：V0.1（最小可行版本）
- 状态：已评审定稿

## 1. 目标与范围

### 1.1 产品目标

V0.1 只有一个目标：**上传一部小说（EPUB）→ 输入/选择人物 → 返回该人物的关系网络图**。

远期愿景（V0.1 明确不做）：长篇小说 → 人物/事件/关系抽取 → 动态知识图谱 → 用户选择人物 → 展示人物关系网络，并支持沿关系和剧情回溯。V0.2+ 再逐步补齐别名归并（Alias/Entity Resolution）、时间线、事件演化、GraphRAG、Rerank 等。

### 1.2 明确不做（YAGNI）

- 100 万字级处理优化
- GraphRAG / Rerank
- 时间线 / 事件演化
- 多用户 / 权限
- 分布式 / 微服务
- Redis 等外部任务存储
- 事件驱动/消息队列
- 人物别名归并（V0.1 中 LLM 输出的不同写法视为不同 Person）

### 1.3 V0.1 数据流

```
EPUB
  ↓  epub_reader：按 spine 解析为章节
章节 (chapter_id, chapter_title, text)
  ↓  chunker：切块（含章节内字符偏移）
Chunk[]
  ↓  extractor：并发调用 LLM，强制结构化 JSON 输出
ChunkExtraction (Pydantic 校验)
  ↓  merger：块内去重 + 跨块聚合
人物 + 关系（带 weight/confidence/evidence）
  ↓  db：写 Neo4j
图数据
  ↓  FastAPI API
JSON 子图
  ↓  React 前端
人物关系图
```

## 2. 技术栈与部署

| 层 | 选型 | 说明 |
|---|---|---|
| LLM | OpenAI 兼容云 API | 如 DeepSeek / 通义 / OpenAI，通过 `base_url` + `api_key` + `model` 配置 |
| 后端 | Python 3.11+ / FastAPI | 单进程；Neo4j 官方 Python driver |
| 前端 | React + Vite + TypeScript + react-force-graph-2d | Vite dev 代理 `/api` → `http://localhost:8000` |
| 图数据库 | Neo4j Community 5.x（Docker Compose） | 端口 7474/7687，数据卷持久化 |
| 配置 | `.env` | 见 §7 配置项 |

## 3. 数据模型（Neo4j）

### 3.1 节点

**Novel**

```
Novel { id: uuid, title: str, chapters: [{id: int, title: str}] }
```

- 章节元信息（chapter_id → title 映射）由**应用层**维护，存放在 Novel 节点属性上
- Person / 关系只存 `chapter_id` 编号，不存章节标题

**Person**

```
Person { id: uuid, novel_id: str, name: str, mention_count: int, chapters: [int] }
```

- `id`（UUID）是 API 主键，`name` 只是显示属性
- `chapters` 为该人物出现的章节编号列表（去重）
- V0.1 不做别名归并：LLM 输出什么名字就是什么 Person；同一小说内 `贾宝玉` 与 `宝玉` 是两个节点

### 3.2 关系（边）

```
(:Person)-[:RELATES_TO]->(:Person)
RELATES_TO {
  type:       枚举（见 §4.3），
  confidence: float，= 所有独立确认该关系的 chunk 的 confidence 算术平均值（V0.1 不做加权平均），
  weight:     int，= 确认该关系的不同 chunk 数量（distinct chunk_id 数），
  chunk_ids:  [int]，确认该关系的 chunk_id 去重集合，
  evidence:   [{chunk_id, chapter_id, text}]，按首次发现顺序保留前 5 条
}
```

**weight 语义（明确定义）**：`weight = 该关系被多少个不同文本块（chunk）独立确认`。

- 同一 chunk 内 LLM 重复输出同一 `(source, target, type)` 只计一次
- 不同 chunk 确认则各 +1，最终 `weight = len(chunk_ids)`
- 防止模型重复输出污染权重

**evidence 追加规则（明确定义）**：按**首次发现顺序**保存前 5 条；第 6 条起不再追加 evidence，但 `chunk_ids.add()` 与 `weight += 1` 照常进行。

**confidence 语义（明确定义）**：所有独立确认该关系的 chunk 的 confidence 的算术平均值。例：chunk1→0.95、chunk2→0.90、chunk3→0.70，最终 confidence = 0.85。V0.1 不引入按文本长度、章节重要性、模型概率的加权平均。

**方向语义（明确定义）**：保留有向边，方向仅表示抽取时「主体 → 客体」（source = 当前文本片段中作为关系主体的人物，target = 与其发生关系的人物），**不赋予通用语义**，不处理对称关系。

### 3.3 约束（以实际 Neo4j 版本文档为准）

Neo4j Community 5.x，docker-compose 固定版本（如 `neo4j:5.26-community`，以可用镜像为准），约束语法：

```cypher
CREATE CONSTRAINT person_id IF NOT EXISTS
FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT person_novel_name IF NOT EXISTS
FOR (p:Person) REQUIRE (p.novel_id, p.name) IS UNIQUE;
```

- `UNIQUE(Person.id)`：API 主键
- `UNIQUE(Person.novel_id, Person.name)`：同一小说内人名唯一；不同小说的同名人物是两个节点

### 3.4 隔离原则

**所有 Neo4j 查询都必须带 `novel_id`**。即使 `character_id` 是全局 UUID，关系查询也采用 `novel_id + character_id` 双层隔离，保证多小说架构从第一版就是安全的。

## 4. 抽取管线

模块：`pipeline/epub_reader.py`、`pipeline/chunker.py`、`pipeline/llm_client.py`、`pipeline/extractor.py`、`pipeline/merger.py`，各模块只通过明确的数据结构通信。

### 4.1 epub_reader

- 使用 `ebooklib` 按 spine 顺序解析 EPUB 的 XHTML
- 输出：按顺序编号的章节列表 `[(chapter_id, chapter_title, plain_text)]`
- 章节标题取自 EPUB 内章节标题（去重/清洗），chapter_id 从 1 开始按 spine 顺序递增

### 4.2 chunker

**Chunk 内部结构（固定）**：

```
Chunk(
    chunk_id: int,        # 全局递增
    chapter_id: int,
    chapter_title: str,
    text: str,
    start_offset: int,    # 相对「该章节纯文本」的字符偏移
    end_offset: int,
)
```

- offset 定义为**相对于该章节纯文本**的字符偏移，不做整本 EPUB 偏移（V0.1 最简单、最易排查）
- 切分规则：整章 ≤ `CHUNK_SIZE`（默认 4000 字）为一块；超长章按 `CHUNK_SIZE` 切 + `CHUNK_OVERLAP`（默认 400 字）重叠
- `chapter_title` 随 Chunk 携带，仅供排查，API 不返回

### 4.3 LLM 输出契约（schemas/llm.py，Pydantic 严格校验）

```python
class RelationshipType(str, Enum):
    love = "love"
    family = "family"
    friendship = "friendship"
    enmity = "enmity"
    alliance = "alliance"
    mentorship = "mentorship"
    other = "other"

class Character(BaseModel):
    name: str = Field(min_length=1, max_length=50)

class Relationship(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)

class ExtractionResult(BaseModel):
    characters: list[Character]
    relationships: list[Relationship]
```

**业务校验**：
- `source != target`：self-loop（如 贾宝玉 → 贾宝玉）直接丢弃
- type 只允许 7 个枚举值，`other` 为兜底

**强制结构化**：调用时使用 `response_format={"type": "json_object"}`（OpenAI 兼容 API 支持），Prompt 明确输出 schema；**不允许**让 LLM 自由文本 + Python 正则解析。流程固定为：LLM JSON → Pydantic → 校验 → Neo4j。

**Prompt 硬性要求**：
- 只能使用上述 7 个枚举值，禁止自创类型（如 `romantic`、`lover`、`亲密`、`爱情`、`love_relation` 全部统一到 `love`）
- source = 当前文本片段中作为关系主体的人物；target = 与其发生关系的人物
- 只抽取文本片段中明确出现的人物与关系，不臆测

### 4.4 extractor

- 并发调用 LLM，并发数由配置 `LLM_CONCURRENCY`（默认 4）控制，**代码中不写死**
- 每个 chunk 一次调用，输出经 Pydantic 校验
- 失败分类处理：
  - **429 / 5xx（服务端/限流错误）**：重试 1 次（带简单退避）；仍失败 → 记 failed_block
  - **Pydantic validation error（结构化输出失败）**：不重试，直接记 failed_block
- 失败块：结构化记录 `{chunk_id, chapter_id, error}`，`error` 如 `"validation_error"`、`"http_429"`、`"http_500"`；**LLM 原始返回内容不进入 Job API**，只写入服务端日志
- 单块失败不阻塞整本；全部失败 → job 标记 `failed`

### 4.5 merger

- **唯一输入单位：chunk_id**。按 `(novel_id, source, target, type, chunk_id)` 做块内去重：
  - 同一 chunk 重复输出同关系只计一次
  - 不同 chunk（如 1、7、12）→ `weight = 3`、`chunk_ids = [1, 7, 12]`
- 跨块聚合：
  - `weight = len(chunk_ids)`
  - `confidence` = 各确认 chunk confidence 的算术平均
  - `evidence` 按首次发现顺序保留前 5 条
- 人物聚合：按 name 精确归并（V0.1 不做别名解析），`mention_count` = 出现块数，`chapters` = 去重章节列表
- 此逻辑由 `tests/unit/test_merger.py` 锁死

### 4.6 写库（db/neo4j.py）

- 启动时（或首次入库前）确保两个唯一约束存在（见 §3.3）
- MERGE 人物：按 `(novel_id, name)`；写入/更新 `id`（首次生成 UUID）、`mention_count`、`chapters`
- MERGE 关系：按 `(novel_id, source, target, type)`，追加 `chunk_ids`（并集）、更新 weight/confidence/evidence
- 写入 Novel 节点及章节元信息

## 5. 后端 API（schemas/api.py）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/novels` | POST | multipart 上传 .epub → 创建 Novel + 启动后台 ingest 任务 → `{novel_id, job_id}` |
| `/api/jobs/{job_id}` | GET | 任务状态与进度（见 §5.1） |
| `/api/novels/{novel_id}` | GET | 小说元信息：标题、章节列表 `[{id, title}]`、人物/关系统计 |
| `/api/novels/{novel_id}/characters?q=` | GET | 模糊搜索人物候选 `[{id, name, mention_count}]`（前端联想） |
| `/api/characters/{character_id}/graph` | GET | 1 跳子图（见 §5.2） |
| `/api/health` | GET | 健康检查（含 Neo4j 连通性） |

### 5.1 Job 状态（models/job.py）

**Job 状态枚举（固定）**：

```
pending | running | completed | completed_with_errors | failed
```

- `completed`：所有 chunk 成功
- `completed_with_errors`：至少一个 chunk 失败，但仍成功生成图谱
- `failed`：所有 chunk 失败，或 EPUB 解析失败 / Neo4j 不可用等致命错误

**Job 响应结构**：

```json
{
  "status": "running",
  "progress": { "done_chunks": 96, "total_chunks": 100 },
  "failed_blocks": [ { "chunk_id": 83, "chapter_id": 17, "error": "validation_error" } ],
  "stats": { "persons": 128, "relationships": 342 }
}
```

**Job 存储**：V0.1 存内存字典 `jobs: dict[str, JobState]`（单进程 FastAPI 足够，不引入 Redis）。`JobState` 为 Pydantic 内部模型（不做 ORM）。

> **README 必须明确记录**：Job state is process-local in V0.1 and will be replaced by a persistent task store in later versions.

### 5.2 1 跳子图响应

```json
{
  "nodes": [
    { "id": "uuid", "name": "贾宝玉", "mention_count": 42, "is_center": true }
  ],
  "edges": [
    {
      "source_id": "uuid-a",
      "target_id": "uuid-b",
      "type": "love",
      "weight": 3,
      "confidence": 0.85,
      "evidence": [ { "chapter_id": 3, "chapter_title": "贾雨村夤缘复旧职", "text": "贾宝玉和林黛玉谈话……" } ]
    }
  ]
}
```

- 查询：`novel_id + character_id` 双层隔离，取该人物 1 跳内所有邻居及其边
- 人物名匹配流程：前端输入 → `/characters?q=` 联想 → 用户点选拿 `character_id` → 查 graph；后端不做名字模糊匹配，只认 UUID
- 不存在的 `character_id` → 404

## 6. 前端

技术：React + Vite + TypeScript + react-force-graph-2d。

### 6.1 页面流程（单页）

1. **上传区**：拖拽/选择 .epub → `POST /api/novels`
2. **进度条**：固定 1s 轮询 `GET /api/jobs/{id}`，**只显示** `done_chunks / total_chunks` + 百分比（如「37 / 86 chunks · 43%」）；不做当前章节名、LLM Token、预计剩余时间等噪音信息；不用 WebSocket
3. **完成统计**：人物数、关系数；`completed_with_errors` 时提示失败块数
4. **人物搜索**：输入联想（`/characters?q=`，防抖），下拉候选（名称 + 出现块数）→ 点选 → `GET /api/characters/{id}/graph`
5. **关系图**：
   - 节点大小 ∝ `mention_count`，中心人物高亮
   - 边按 `type` 着色，悬浮显示 `type / weight / confidence`
   - 点击边 → 侧栏显示 evidence（章节标题 + 原文片段）
   - 点击非中心节点 → 切换中心人物，重新请求子图

### 6.2 薄转换层（前端内部类型）

force-graph 内部状态与后端 DTO 隔离，后端响应先转换为前端类型：

```ts
type GraphNode = {
  id: string;
  name: string;
  mention_count: number;
  isCenter?: boolean;
};

type GraphLink = {
  source: string;
  target: string;
  type: string;
  weight: number;
  confidence: number;
  evidence: Evidence[];
};
```

## 7. 配置项（.env.example）

| 配置 | 默认 | 说明 |
|---|---|---|
| `BAILIAN_API_KEY` | 必填 | 阿里百炼 API Key（缺失则启动时报错退出） |
| `BAILIAN_URL` | 必填 | 百炼 OpenAI 兼容地址（如 `https://dashscope.aliyuncs.com/compatible-mode/v1`） |
| `BAILIAN_MODEL` | qwen3.7-max-2026-05-17 | 模型名（可覆盖） |
| `LLM_CONCURRENCY` | 4 | LLM 并发数（可按模型限流调整 4/8/16） |
| `CHUNK_SIZE` | 4000 | 切块字数 |
| `CHUNK_OVERLAP` | 400 | 切块重叠字数 |
| `NEO4J_URI` | bolt://localhost:7687 | Neo4j 地址 |
| `NEO4J_USER` / `NEO4J_PASSWORD` | neo4j / 必改 | Neo4j 凭据 |

> 说明：V0.1 原配置 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 已改为阿里百炼专用 `BAILIAN_*`（2026-08-21 修订）；`llm_client` 请求携带 `Authorization: Bearer <BAILIAN_API_KEY>`。

## 8. 错误处理

| 场景 | 行为 |
|---|---|
| 上传非 .epub / 空文件 / EPUB 解析失败 | 400 + 明确错误信息 |
| 单个 chunk 的 LLM 调用失败（429/5xx） | 重试 1 次（带退避）后记 `failed_block`，任务继续 |
| 单个 chunk 校验失败（validation error） | 不重试，记 `failed_block`；原始 LLM 输出仅写服务端日志 |
| 所有 chunk 失败 | job → `failed`，返回原因 |
| 部分 chunk 失败但图谱生成成功 | job → `completed_with_errors` |
| Neo4j 不可达 | `/api/health` 与 ingest 均返回 503 |
| LLM api_key / base_url 缺失 | 应用启动时校验并报错退出 |
| 查询不存在的 character_id | 404 |

## 9. 测试

### 9.1 单元测试（`pytest` 默认只跑这些，不依赖 Neo4j / 真实 LLM）

- `tests/unit/test_chunker.py`：EPUB→章节→切块；超长章回退；chunk_id 递增；offset 为章节内字符偏移
- `tests/unit/test_merger.py`：**锁死 weight 语义**——同 chunk 重复输出只计一次；不同 chunk 聚合 weight/chunk_ids/confidence 平均/evidence 首现前 5 条；self-loop 丢弃
- `tests/unit/test_llm_client.py`：JSON 解析；Pydantic 校验失败 → 不重试；429/5xx → 重试 1 次（mock LLM client，不碰真实 API）

### 9.2 集成测试（需要真实 Neo4j）

- `tests/integration/test_api_neo4j.py`，标记 `@pytest.mark.integration`
- 冒烟用例：上传小样 .epub → job 完成 → `/characters/{id}/graph` 返回 1 跳子图
- 运行方式：`pytest tests/integration` 或 `pytest -m integration`

### 9.3 前端与端到端

- V0.1 前端不写单测，提供手动验收清单
- 端到端手工验收：上传一部公版小说 epub（如《红楼梦》节选）→ 搜索「贾宝玉」→ 看到关系图与 evidence

## 10. 目录结构

```
Long-Novel-Intelligence/
├── docker-compose.yml            # Neo4j Community 5.x
├── .env.example
├── README.md                     # 含 Job state process-local 说明
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── novels.py
│   │   │   ├── jobs.py
│   │   │   ├── characters.py
│   │   │   └── health.py
│   │   ├── pipeline/
│   │   │   ├── epub_reader.py
│   │   │   ├── chunker.py
│   │   │   ├── llm_client.py
│   │   │   ├── extractor.py
│   │   │   └── merger.py
│   │   ├── db/
│   │   │   └── neo4j.py
│   │   ├── schemas/
│   │   │   ├── llm.py            # LLM 输出契约
│   │   │   └── api.py            # HTTP Request/Response
│   │   └── models/
│   │       └── job.py            # 内部任务状态模型（Pydantic，非 ORM）
│   └── tests/
│       ├── unit/
│       │   ├── test_chunker.py
│       │   ├── test_merger.py
│       │   └── test_llm_client.py
│       └── integration/
│           └── test_api_neo4j.py
└── frontend/
    ├── package.json
    └── src/
        ├── App.tsx
        ├── api.ts
        ├── types.ts              # GraphNode / GraphLink 薄转换层
        └── components/
            ├── Upload.tsx
            ├── Progress.tsx
            ├── CharacterSearch.tsx
            └── GraphView.tsx
```

## 11. 非目标（后续版本方向）

- V0.2：Alias / Entity Resolution（别名归并）、有向/无向关系语义、事件抽取与时间线、Chapter 独立建模
- 后续：GraphRAG、Rerank、多用户与权限、持久化任务存储、分布式
