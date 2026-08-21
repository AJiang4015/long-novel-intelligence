# 已有小说恢复能力（Existing Novel Recovery）— 设计文档

- 日期：2026-08-21
- 状态：已评审定稿（含用户 3 条补充约束）
- 场景：Neo4j 中已存在 Novel 数据，但后端/前端重启后，前端强制进入空态并弹上传抽屉，无法访问已有小说。

## 1. 目标与范围

只增加「已有小说恢复」能力：前端启动时探测 Neo4j 中已有小说，按 0 / 1 / 多本三分支处理。

**不改**：Novel 数据模型（无 created_at，不新增字段）、现有上传流程（UploadDrawer 原样）、Graph API（getGraph）、`restoreCenter`（`wb-center:{novel_id}` 恢复逻辑）、GraphCanvas/GraphPanel/DetailsPanel/Topbar、后端 `POST /api/novels` 与 `GET /api/novels/{id}`。

## 2. 三分支恢复策略（用户确认）

| 已存在小说数 | 行为 |
|---|---|
| 0 | 空态 + 自动弹 UploadDrawer（现有行为） |
| 1 | 自动恢复：`getNovel(id)` → phase=graph → 复用 `restoreCenter`（有 `wb-center:{novel_id}` 则恢复中心并拉图；无则 GraphPanel 显示「选择人物」空态，**不得重新打开 UploadDrawer**） |
| 多本 | 显示 ExistingNovelPicker 选择器，选中后走与单本相同的恢复流程 |

不依赖 Neo4j internal id 判断"最新"；列表按 `title` 排序（确定性）。

## 3. 后端设计

| 文件 | 改动 |
|---|---|
| `backend/app/db/neo4j.py` | 新增 `list_novels() -> list[dict]`：`MATCH (n:Novel) RETURN n.id AS id, n.title AS title ORDER BY n.title` |
| `backend/app/schemas/api.py` | 新增 `NovelListItem(BaseModel): id: str; title: str` |
| `backend/app/api/novels.py` | 新增 `GET /api/novels` → `list[NovelListItem]`（空路径精确匹配，与 `GET /{novel_id}` 无冲突） |
| `backend/tests/integration/test_api_neo4j.py` | 追加 2 个测试：空库返回 `[]`；`db.upsert_novel` 造 2 本 → 返回 2 条且按 title 升序（测试后用 `delete_novel` 清理） |

## 4. 前端设计

| 文件 | 改动 |
|---|---|
| `frontend/src/types.ts` | 新增 `NovelListItem { id: string; title: string }`（纯新增 DTO） |
| `frontend/src/api.ts` | 新增 `listNovels(): Promise<NovelListItem[]>`（现有 5 函数不动） |
| `frontend/src/components/ExistingNovelPicker.tsx`（新建） | props `{ open: boolean; novels: NovelListItem[]; onClose: () => void; onSelect: (novel: NovelListItem) => void }`。复用 UploadDrawer 的 drawer 视觉结构（`.drawer-overlay/.drawer/.drawer-head/.drawer-body`），标题「选择已有小说」，列表行用 `.panel` + 标题 + ArrowRightIcon（hover 高亮）。**极简**：只展示小说列表与选择操作，不加搜索/最近使用/章节数等。**只渲染与回调，不承担业务逻辑**；UploadDrawer 本体不动 |
| `frontend/src/App.tsx` | 新增 `pickerOpen` 状态；**启动探测 effect**（mount 一次，cancelled flag）：`listNovels()` → 0=空态+自动抽屉 / 1=`loadNovel(item)` / 多本=`pickerOpen=true`；失败静默回退空态+抽屉，同时 `console.warn` 保留诊断日志（Neo4j/API 不可用排查） |
| `frontend/src/App.tsx` | 新增 `loadNovel(item)`：`getNovel(item.id)` → setNovel → phase=graph → 复用现有 `restoreCenter(novel.id)`（无中心则不设 center，GraphPanel 显示「选择人物」空态，不弹抽屉）；`onPickerSelect` → loadNovel |
| `frontend/src/components/LeftSidebar.tsx` | 统计回退（恢复场景 job=null）：人物/关系改 `job?.stats ?? novel?.stats`；章节 `novel.chapters.length`；**文本块 `job?.progress.total_chunks ?? "—"`**；novel-card 状态文本恢复时显示「已完成」 |

## 5. 用户补充约束（强制）

1. 有 Novel 但无 `wb-center:{novel_id}`：phase=graph，GraphPanel「选择人物」空态；**不得重新打开 UploadDrawer**。
2. `listNovels()` 失败：静默回退 empty + UploadDrawer，但保留 console 诊断日志（`console.warn`，含错误信息）。
3. ExistingNovelPicker 极简：仅列表 + 选择，无搜索/最近使用/章节数等额外功能。

## 6. 验证

- 集成测试：`cd backend && python -m pytest -m integration`（含新增 list_novels 空/非空/排序用例，全量 10+ passed）
- 前端构建：`cd frontend && npm run build`（tsc + vite）
- 三态启动验收（运行全栈 + 真实 Neo4j 数据）：
  1. **0 本**：Neo4j 无 Novel → 前端空态 + 自动弹上传抽屉
  2. **1 本**：Neo4j 有 1 本 → 前端自动恢复 graph（有 `wb-center:{novel_id}` 恢复中心；无则「选择人物」空态且不弹抽屉）
  3. **多本**：Neo4j 有 ≥2 本 → 前端显示选择器，选中后恢复 graph
- 后端未启动时刷新 → 空态 + 抽屉 + console 诊断日志

## 7. 非目标

- 小说切换器（已有小说的常驻选择入口）、删除/管理小说、created_at 时间字段
- 选择器内搜索、最近使用、按时间排序
