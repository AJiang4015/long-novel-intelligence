# 前端 UI 重构设计（按 OpenDesign 已验收设计）— V0.1 修订版

- 日期：2026-08-21
- 状态：已评审定稿（含用户 2026-08-21 增补约束）
- 唯一事实来源：`DESIGN.md`、`design/design-system.html`、`design/novel-graph-workbench.html`

## 1. 目标与范围

将现有 React V0.1 前端按 OpenDesign 已验收设计进行 UI 重构：三栏工作台（Topbar + 左侧栏 + 中央关系图 + 右侧详情栏）+ 上传抽屉 + 完整状态体系。

**明确不变**（重构红线）：
- `api.ts` 全部 5 个函数（uploadNovel / getJob / getNovel / searchCharacters / getGraph）签名与路径
- `types.ts` 全部后端 DTO（JobResponse / NovelResponse / CharacterCandidate / GraphNode / GraphEdge / GraphResponse / Evidence / JobStatus / JobProgress / FailedBlock）
- EPUB 上传校验与提交业务逻辑、1s 轮询逻辑、300ms 防抖搜索逻辑、节点点击切换中心逻辑、边点击选择逻辑、evidence 数据结构
- 后端 API / DTO / 数据库：零改动
- V0.1 范围不扩张，不新增业务功能

**明确改变**：
- 布局（topbar + 三栏 shell + ≤1180px / ≤980px 断点）
- 全部 CSS（token 化，替换 Vite 模板残留）
- 全部 UI 组件（OpenDesign 组件类）
- Graph 渲染层：react-force-graph-2d → **自定义 SVG GraphCanvas**（同心圆固定布局）
- 删除仅服务旧渲染器的 `ForceNode / ForceLink / toForceGraph` 转换代码
- Loading / Empty / Error / Hover / Active / Selected 全部状态

## 2. 组件树与文件结构

```
frontend/src/
├── main.tsx                  （不变）
├── index.css                 （重写：token + reset + 全部组件类，从两个 HTML 提取）
├── App.css                   （删除：Vite 模板残留）
├── App.tsx                   （重写：工作台壳 + 状态机；持有数据/加载/中心/选中边）
├── api.ts                    （不变）
├── types.ts                  （保留全部 DTO；删除 ForceNode/ForceLink/toForceGraph）
└── components/
    ├── Topbar.tsx            品牌 / 小说 chip / 状态 badge / 上传按钮 / 设计系统链接
    ├── LeftSidebar.tsx       novel-card · progress-card · stats-grid · CharacterSearch · center-chip · foot
    ├── CharacterSearch.tsx   重写样式（.search/.suggest、250ms、命中高亮、Esc/外部关闭）
    ├── GraphPanel.tsx        中央容器：toolbar + GraphCanvas + legend + 加载/处理遮罩 + hint
    ├── GraphCanvas.tsx       受控纯 UI 组件：SVG 渲染 + 布局 + 缩放 + 拖拽平移 + hover + 点击回调
    ├── GraphLegend.tsx       右上浮层（7 类型色/线型）
    ├── DetailsPanel.tsx      右侧 380px：关系摘要 + meta 网格 + 原文证据 + 空态
    ├── UploadDrawer.tsx      上传抽屉（dropzone/文件行/错误条/开始分析）
    ├── Toast.tsx             完成/信息提示
    ├── EmptyState.tsx / Spinner.tsx / ErrorBanner.tsx   通用状态件
    └── icons.tsx             内联 SVG monoline 图标库
```

## 3. 状态机与数据流（App 持有数据，组件纯 UI）

**App 状态**：

```
phase: "empty" | "processing" | "graph"     // empty = 无小说，三栏骨架 + 空态 + 自动弹抽屉
novel: NovelResponse | null                 // 完成后 getNovel 填充顶栏/侧栏/统计
job: JobResponse | null                     // 1s 轮询结果（stats / progress.total_chunks）
center: CharacterCandidate | null
selectedEdge: GraphEdge | null              // 详情栏联动
drawerOpen: boolean
graphLoading: boolean                       // 切换中心时的真实加载态
graphError: string | null
```

**数据流**：

```
抽屉上传 → POST /api/novels → phase=processing
  → 1s 轮询 getJob（顶栏 badge + 左侧进度卡 + 中央遮罩三处联动）
  → completed / completed_with_errors → getNovel → phase=graph + toast
  → failed → error-banner + 回退
搜索人物（左侧）→ 点选 → 切换中心 → 持久化 → getGraph → 渲染
  → 点邻居 → 切换中心；点边 → selectedEdge → DetailsPanel 联动
```

**中心人物持久化**：`localStorage` key = `wb-center:{novel_id}`，值为 character UUID。恢复仅在**同一 novel_id** 下生效（切换小说不串中心）。恢复时机：`phase=graph` 且当前 novel 有已存中心时。

**加载时序（真实，禁止假加载）**：

```
click 邻居 → setGraphLoading(true) → await getGraph() → setGraphLoading(false)
```

不做 setTimeout 假延迟；不做人为最小展示时长。加载遮罩显示在真实请求期间（约 320ms 是请求自然时长量级）。

## 4. GraphCanvas（受控纯 UI 组件）

**接口**：

```tsx
interface GraphCanvasProps {
  graph: GraphResponse;            // 唯一图数据来源，App 传入
  centerId: string;
  selectedEdge: GraphEdge | null;  // 选中边（App 持有）
  onNodeClick: (id: string) => void;   // 点击邻居 → 切换中心（App 处理）
  onEdgeClick: (edge: GraphEdge) => void;  // 点击边 → 选中（App 处理）
}
```

GraphCanvas **内部负责**：布局计算、SVG 渲染、缩放（按钮 0.5–2.5 ×1.25 + 适应）、基础鼠标拖拽平移、hover、edge hit area、edge label。**不负责**：数据获取、业务状态、业务回调——纯 UI。

**渲染规则**（从 workbench 提取，保持已验收视觉）：

- 画布 `viewBox="0 0 900 600"`、`preserveAspectRatio="xMidYMid meet"`；点阵网格背景（CSS `radial-gradient(var(--border) 1px, transparent 1px)` 22px）
- 布局：中心 (450,300)；邻居角度 `-π/2 + (i/n)×2π`，`R = min(212, 110 + 邻居数×10)`
- 中心节点：r=20，accent 填充 + 白描边 3px + accent-soft 外环（r+8）；名称 12.5px/600 位于 y=r+22
- 邻居节点：`r = round(8 + sqrt(mention_count/982)×9)`（8–17px），surface 填充 + border-2 描边 1.6；名称 12.5px/500；hover 描边转 accent 2.4 + 轻投影
- 边：宽度 `clamp(2.2, 1+log2(weight+1)×0.42, 3.4)`；类型色 + 线型（love/family/friendship/alliance 实线、enmity 虚线 7 5、mentorship 点线 1 5、other 细点线 2 4）；边标签 pill（中点，surface 底 + border-2 描边，类型名 11px/600 类型色）；16px 透明命中线（edge-hit）
- 选中态：该边加粗 4px；`has-selection` 时其余边 opacity .32、其余标签 opacity .35
- 缩放：`translate(450,300) scale(z) translate(-450,-300)` + 平移 offset；z∈[0.5,2.5]；按钮 ×1.25 / 适应复位；**基础鼠标拖拽平移**（pointer 事件，简单实现，不引入复杂交互）
- tooltip：深色卡片（oklch 24%/.96 底），节点=名称+提及，边=类型色点+类型+weight/conf/证据数；跟随指针、防溢出翻转
- 孤立人物（1-hop 无邻居）：显示空态提示（设计 §8.9），不渲染空圆

## 5. 全局样式与 token

- `index.css` 整体替换：`:root` 令牌（oklch 全量：--bg/--surface/--elevated/--border/--border-2/--fg/--text-2/--muted/--accent-*/--success-*/--warning-*/--danger-*/--neutral-soft/--rel-* 七类型/--font-*/--fs-*/--sp-*/--r-*/--sh-*/--z-*）+ reset + 通用组件类（.btn 五变体/.input/.field/.badge/.rel-badge/.panel/.section-title/.stat-cell/.progress/.empty/.spinner/.error-banner/.tooltip/.drawer/.dropzone/.file-row/.toast/.search/.suggest/.graph-*）+ 应用壳（.topbar/.shell/.left/.center/.right）+ 断点（≤1180px、≤980px 堆叠）
- 组件内**禁止**硬编码 hex / 裸色值，一律 `var(--*)` / `color-mix()`
- 数字统一 `.num`（mono + tabular-nums）
- **千分位格式（强制）**：逗号分隔（`1,000`），禁止空格（`1 000`）。实现用确定性格式化避免 locale 差异：`fmt = (n: number) => n.toLocaleString("en-US")`（en-US 恒定输出逗号）。
- 顶栏「设计系统」链接：`design/design-system.html` 复制进 `frontend/public/`，dev 下 `/design-system.html` 可访问

## 6. 实施顺序

1. `index.css` 全面替换（token + 组件类 + 壳 + 断点）——先决步骤
2. 基础件：`icons.tsx` / `EmptyState` / `Spinner` / `ErrorBanner` / `Toast`
3. `Topbar` + `UploadDrawer`（抽屉复用现有 Upload 校验/提交逻辑）
4. `LeftSidebar`（novel-card / progress-card / stats / search / center-chip）+ `CharacterSearch` 重写样式
5. `App.tsx` 壳重构（三栏 + phase 状态机 + getNovel + localStorage 作用域持久化）
6. `GraphPanel` + `GraphCanvas`（SVG 渲染 + 缩放 + 拖拽平移 + tooltip + legend）+ `GraphLegend`
7. `DetailsPanel`（关系详情 + evidence + 空态）
8. 清理：删除 `App.css`；删除 `types.ts` 中 ForceNode/ForceLink/toForceGraph；删除 `GraphView.tsx`；移除 `react-force-graph-2d` import（`package.json` 依赖条目暂留，注明清理债：沙箱内 npm install 有 vite 补丁风险，待正常环境一次性移除并同步 lock）
9. 验证：`tsc + vite build` 通过；对照 `design/novel-graph-workbench.html` 逐项验收

## 7. 验证清单（对照 workbench 逐项）

- [ ] 三栏工作台布局（topbar / left / center / right）与断点行为
- [ ] 顶栏：品牌、当前小说 chip、状态 badge、上传按钮、设计系统链接
- [ ] 左侧：小说卡、进度卡（处理中）、2×2 统计（千分位逗号）、人物搜索联想、中心人物卡
- [ ] 中心人物与 1-hop 同心圆布局（中心高亮 / 邻居按提及数缩放）
- [ ] edge hit area（16px 命中）
- [ ] edge label（类型 pill）
- [ ] hover（节点/边）
- [ ] selected edge（加粗 + 其余淡化 + 详情栏联动）
- [ ] zoom（按钮放大/缩小/适应）与基础拖拽平移
- [ ] node click 切换中心（真实加载遮罩）
- [ ] evidence panel（关系摘要 + meta 网格 + 原文证据 + 空态）
- [ ] 上传抽屉（拖拽/文件行/非 epub 错误/开始分析）
- [ ] toast、loading spinner、error banner、empty state
- [ ] 数字格式全部逗号千分位（`1,000`，无空格）
- [ ] `wb-center:{novel_id}` 持久化仅在同小说内恢复

## 8. 约束（用户确认）

1. GraphCanvas 只负责 UI 渲染与交互，不引入新的业务状态
2. GraphResponse 是唯一图数据来源
3. 保留按钮缩放与基础鼠标拖拽平移；不增加复杂交互
4. 节点点击、边点击、中心人物切换保持现有行为
5. 不因更换渲染器修改 API / DTO / 后端
6. 完成后重点验证中心/1-hop/hit area/edge label/hover/selected/zoom/node click/evidence panel
7. 如需改动 Graph 数据类型，保持最小变更，不引入新领域模型
8. 加载为真实时序，禁止假加载 setTimeout

## 9. 非目标（V0.2+）

- 时间线 / 事件演化（V0.2）、复杂关系类型（V0.4）
- 滚轮缩放、双击缩放、多选、框选等复杂图交互
- 节点自定义图片、动画边
