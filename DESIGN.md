# DESIGN.md — 人物关系图谱分析工作台（React UI 实现 · 单一事实来源）

> **来源**：`design-system.html` + `novel-graph-workbench.html`（已验收通过）
> **用途**：Coding Agent / 后续实现 React UI 时唯一的视觉与交互依据。
> **规则**：本文件记录的值与规则**均已存在于上述两个 HTML 文件**。实现时不得引入本文件之外的 Token、色值、字体、间距、圆角、阴影或视觉模式；不得新增业务功能。

---

## 1. Product Visual Direction

| 维度 | 取值 |
|---|---|
| 方向 | tech-utility（GitHub / Datadog / Sentry / Cloudflare Dashboard 类） |
| 产品气质 | 专业数据分析工具 / Knowledge Graph Explorer / Research Tool |
| 目标平台 | Desktop-first Web Application（不优先移动端，仍提供降级断点） |
| 信息密度 | 适中偏高，数据优先，长时间使用舒适 |
| 视觉基调 | 专业、克制、稳定、可信；强调内容与关系图，而非装饰 |

实现时遵循：

- 界面是工具的工作台，不是营销页面，也不是 Chat UI。
- 所有数字使用等宽 `tabular-nums`。
- 仅一个强调色（accent），功能性地出现（主按钮、中心节点、焦点环、链接 hover）。
- 用发丝线（hairline）与留白组织信息，不用色块卡片堆叠。
- 动效克制：仅 0.12–0.3s 的状态过渡，无装饰性动画。

---

## 2. Layout

### 2.1 整体骨架（应用壳）

```
┌────────────────────────────────────────────────────────────┐
│ 顶部产品栏 (topbar) · 52px · surface · 底部发丝线           │
├───────────┬───────────────────────────────┬────────────────┤
│ 左侧栏     │ 中央：关系图                    │ 右侧：详情/证据 │
│ 300px     │ 工具栏 46px + 画布 flex:1       │ 380px          │
│ (≤1180: 276px) │                            │ (≤1180: 348px) │
├───────────┴───────────────────────────────┴────────────────┤
```

- 页面级：`body` 为 `display:flex; flex-direction:column; overflow:hidden; height:100%`——应用壳不产生页面滚动条。
- 三栏网格：`.shell` = `grid-template-columns: 300px minmax(0,1fr) 380px`，`min-height:0`；中央列必须 `min-width:0` 防止溢出。
- 内部滚动：左栏、右栏各自 `overflow-y:auto`；中央画布 `flex:1; min-height:0`。
- 断点：
  - `≤1180px`：`276px minmax(0,1fr) 348px`
  - `≤980px`：堆叠为单列（`grid-template-columns` 失效），画布 `min-height:520px`，右侧栏 `max-height:640px`，隐藏顶部"当前小说"chip。

### 2.2 顶部产品栏（topbar）

- 高 52px；`--surface` 背景；底部 `1px var(--border)` 发丝线。
- 从左到右：
  1. 品牌：24px 圆角图标（accent-soft 底 + accent-strong 图）+ 产品名「人物关系图谱」（14px/600）+ mono 副标「GRAPH WORKBENCH」（11px muted）。
  2. 1px 分隔线（高 20px）。
  3. 当前小说 chip：「当前小说」label（12px muted）+ 小说名（14px/600，超长省略）+ 分析状态 badge。
  4. 右侧操作：`设计系统` 文字链接（12px muted，hover 转 fg）+ 主按钮「上传新小说」。
- 顶栏保持简洁，禁止做成营销型 SaaS Header（无标语、无大 Logo、无多余导航）。

### 2.3 左侧栏（小说信息 / 搜索 / 状态）

- `--bg` 背景，右侧 `1px var(--border)` 发丝线；内边距 `16px`；区块间距 `20px`。
- 自上而下：
  1. **小说信息卡**（panel）：小说名（16px/600）+「演示数据」accent badge；meta 行：章回数 / 文本块数（等宽数字）、分析状态文本。
  2. **分析进度卡**（仅分析中显示）：标题 + `分析中` warning 呼吸 badge + 进度条 + `N / 1,284 块`。
  3. **小说统计**：2×2 统计格（人物 / 关系 / 章节 / 文本块），数值 `--fs-stat` mono/600。
  4. **人物搜索**：搜索框 + 联想下拉（见 §8 Search）。
  5. **当前中心人物**卡：姓名（15px/600）+「中心」accent badge + `提及 N 块` + `1-hop 子图 · N 人物 · M 关系`。
  6. 底部注脚：演示数据说明 + 设计系统链接（13px muted）。

### 2.4 中央关系图区

- `--surface` 背景；工具栏 46px（底部发丝线）+ 画布 `flex:1`。
- 工具栏：左＝「中心人物」label + 姓名（14px/600）+「N 提及」badge +「1-hop」badge；右＝缩放图标按钮组（放大 / 缩小 / 适应）。
- 画布：`position:relative`，内含 SVG（`viewBox="0 0 900 600"`，`preserveAspectRatio="xMidYMid meet"`）、图例浮层（右上）、加载遮罩、分析中遮罩、操作提示 pill（底部居中）。

### 2.5 右侧栏（关系详情 / Evidence）

- `--bg` 背景，左侧发丝线；`overflow-y:auto`。
- 头部 sticky：`关系详情`（13px/600）+ 关闭按钮（选中关系时显示）。
- 内容区 `padding:20px`，见 §10。

---

## 3. Typography

### 3.1 字体族

```css
--font-display: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
--font-body:    -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
--font-mono:    'JetBrains Mono', 'IBM Plex Mono', ui-monospace, 'Cascadia Mono', Consolas, monospace;
```

- 单一无衬线家族（显示与正文同族，靠字重/字号分层）——数据密集型工具允许单家族，不引入衬线显示字体。
- **中文字体回退**：必须包含 `'PingFang SC', 'Microsoft YaHei'`（macOS / Windows），拉丁与数字优先 Inter / 系统栈。
- 等宽族用于：数字、章节号、置信度、权重、任务/标识、mono 副标。
- 全局基线：`font-size:14px; line-height:1.6; color:var(--fg)`；标题 `text-wrap:balance`，段落 `text-wrap:pretty`。
- `.num`（等宽 + tabular）：`font-family:var(--font-mono); font-variant-numeric:tabular-nums`——**所有数字统计必须使用**。

### 3.2 字号层级（应用）

| Token | 值 | 用途 | 字重 |
|---|---|---|---|
| `--fs-title` | 16px | 页面/面板/抽屉标题、中心人物名 | 600 |
| `--fs-h3` | 14px | 次级标题（设计系统页） | 600 |
| `--fs-section` | 13px | 区块标题（`text-transform:uppercase`，字距 0.02em） | 600 |
| `--fs-body` | 14px | 正文、按钮、表单 | 400/500 |
| `--fs-2` | 13px | 次要文本、描述 | 400 |
| `--fs-caption` | 12px | 注释、章节引用、统计标签 | 400/500 |
| `--fs-xs` | 11px | 最小注释、mono 副标 | 400 |
| `--fs-stat` | 22px mono | 统计数字（人物/关系/章节/文本块） | 600 |
| `--fs-stat-lg` | 28px mono | 大号统计（设计系统页展示） | 600 |

- 关系图专用字号：节点名 12.5px（中心 600、邻居 500）；边标签 11px/600；证据正文 14.5px。
- 数字规则：统计、权重、置信度、提及数一律等宽 `tabular-nums`；`toLocaleString("zh-CN")` 千分位格式。

---

## 4. Colors

> 全部以 oklch 定义；派生色一律 `color-mix()`，**禁止在组件中硬编码十六进制或裸色值**。

### 4.1 表面与文本

| Token | 值 | 用途 |
|---|---|---|
| `--bg` | `oklch(97.5% .006 250)` | 页面/工作台背景（冷灰，非纯白） |
| `--surface` | `oklch(100% 0 0)` | 卡片、面板、顶栏、画布 |
| `--elevated` | `oklch(100% 0 0)` | 浮层（联想下拉 / 抽屉 / 工具提示），配合 shadow 区分 |
| `--border` | `oklch(90% .01 250)` | 发丝线、分隔线 |
| `--border-2` | `oklch(84% .012 250)` | 输入框描边、强调分隔 |
| `--fg` | `oklch(24% .025 250)` | 主文本 |
| `--text-2` | `oklch(40% .02 250)` | 次级文本 |
| `--muted` | `oklch(50% .018 250)` | 注释、占位符 |

### 4.2 品牌与状态

| Token | 值 | 用途 |
|---|---|---|
| `--accent` | `oklch(58% .16 145)` | 品牌绿：节点填充、焦点环、图标 |
| `--accent-strong` | `color-mix(in oklch, var(--accent) 78%, black)` | 主按钮填充、链接文本（保证 AA 对比度） |
| `--accent-hover` | `color-mix(in oklch, var(--accent) 68%, black)` | 主按钮 hover |
| `--accent-soft` | `color-mix(in oklch, var(--accent) 12%, white)` | 强调底色 |
| `--success` | `oklch(47% .12 158)` | 完成 / 正常 |
| `--success-soft` | `color-mix(in oklch, var(--success) 10%, white)` | 成功徽标底色 |
| `--warning` | `oklch(55% .12 75)` | 分析中 / 部分失败 |
| `--warning-soft` | `color-mix(in oklch, var(--warning) 13%, white)` | 警告徽标底色 |
| `--danger` | `oklch(52% .17 27)` | 错误 / 失败 |
| `--danger-soft` | `color-mix(in oklch, var(--danger) 10%, white)` | 错误底色 |
| `--neutral-soft` | `color-mix(in oklch, var(--fg) 5%, white)` | 悬停底色、引用块、进度轨道 |

### 4.3 关系类型色（7 类，颜色 + 线型 + 标签三重编码）

| Token | 值 | 类型 | 线型 |
|---|---|---|---|
| `--rel-love` | `oklch(52% .19 12)` | love 爱恋 | 实线 |
| `--rel-family` | `oklch(50% .15 305)` | family 家族 | 实线 |
| `--rel-friendship` | `oklch(50% .14 250)` | friendship 友谊 | 实线 |
| `--rel-enmity` | `oklch(51% .2 28)` | enmity 敌对 | 虚线 `7 5` |
| `--rel-alliance` | `oklch(52% .12 195)` | alliance 同盟 | 实线 |
| `--rel-mentorship` | `oklch(55% .14 70)` | mentorship 师承 | 点线 `1 5`（round） |
| `--rel-other` | `oklch(55% .02 250)` | other 其他 | 细点线 `2 4` |

- 类型徽标底色/描边统一为 `color-mix(in oklch, var(--rel-*) 11%, white)` 与 `color-mix(in oklch, var(--rel-*) 26%, white)`。

### 4.4 对比度约束

- 正文文本 ≥ 4.5:1；大文本与图形 ≥ 3:1。
- 悬停/选中态的文本对比度不得低于默认态（hover 只能加深前景或抬高背景，禁止把前景改成更接近背景的灰色）。
- 主按钮文字为 `--surface`（白）配 `--accent-strong` 深绿底，保证 AA。
- `disabled` 是唯一允许降低对比度的状态（`opacity:.45`）。

---

## 5. Spacing

4pt 网格，统一使用 token，禁止散落魔数：

| Token | 值 | 常见用途 |
|---|---|---|
| `--sp-1` | 4px | 徽标内间距、极细间隔 |
| `--sp-2` | 8px | 图标与文字间隔、badge 内距 |
| `--sp-3` | 12px | 输入内边距、元素组间距 |
| `--sp-4` | 16px | 面板内边距（默认）、表单控件内距 |
| `--sp-5` | 20px | 弹层/抽屉内容内距、较大分组 |
| `--sp-6` | 24px | 区块间距 |
| `--sp-7` | 32px | 页面留白 |
| `--sp-8` | 40px | 大段留白 |
| `--sp-9` | 48px | 文档页区块间距（设计系统页） |

约定：面板内边距默认 `--sp-4`；左右栏区块间距 `--sp-5`；按钮水平内距 `--sp-4`。

---

## 6. Radius

克制：控件 6px、浮层 8px、卡片 10px，胶囊仅用于徽标/进度/提示条。

| Token | 值 | 用途 |
|---|---|---|
| `--r-1` | 4px | 图标块、小型元素 |
| `--r-2` | 6px | **控件**（按钮、输入框、图标按钮） |
| `--r-3` | 8px | **浮层**（联想下拉、工具提示、证据文本块、错误条） |
| `--r-4` | 10px | **卡片 / 面板** |
| `--r-5` | 12px | 抽屉（设计系统页规范） |
| `--r-pill` | 999px | 徽标、进度条、提示 pill |

禁止大面积、夸张圆角（无 20px+ 卡片圆角）。

---

## 7. Shadow

仅三档，按层级从严使用：

| Token | 值 | 用途 |
|---|---|---|
| `--sh-1` | `0 1px 2px oklch(24% .02 250/.05), 0 1px 1px oklch(24% .02 250/.04)` | 行内悬浮（节点 hover、操作提示 pill、图例卡） |
| `--sh-2` | `0 2px 4px oklch(24% .02 250/.05), 0 8px 20px -6px oklch(24% .02 250/.10)` | 联想下拉、工具提示、浮层 |
| `--sh-3` | `0 2px 6px oklch(24% .02 250/.08), 0 12px 32px -8px oklch(24% .02 250/.18)` | 抽屉、覆盖层 |

禁止超出三档的自定义阴影。

---

## 8. Components

> 统一规则：所有可聚焦元素必须有 `:focus-visible` 焦点环（`outline:2px solid var(--accent); outline-offset:2px`）。图标一律内联 SVG（monoline，stroke 1.6–2），禁止 emoji 当图标。

### 8.1 Button

- 尺寸：默认高 `32px`、`--fs-2/500`、水平内距 `--sp-4`、圆角 `--r-2`；大号 `36px`；小号 `28px`；图标按钮 `30×30`（仅图标）。
- 变体与交互（前景/背景成对定义，hover 不得降低对比度）：

| 变体 | 默认 | hover |
|---|---|---|
| `btn-primary` | 底 `--accent-strong`，字 `--surface`，边 `--accent-strong` | 底 `--accent-hover`，边 `--accent-hover` |
| `btn-secondary` | 透明底，字 `--fg`，边 `--border-2` | 边 `--fg`，底 `--neutral-soft` |
| `btn-ghost` | 透明，字 `--text-2` | 字 `--accent-strong`，底 `--accent-soft` |
| `btn-danger-ghost` | 透明，字 `--danger` | 底 `--danger-soft` |
| `btn-icon` | 透明，字 `--text-2` | 字 `--fg`，底 `--neutral-soft`，边 `--border` |

- `:active` 下移 1px；`disabled` 一律 `opacity:.45; cursor:not-allowed`。
- 同一视口内同一动作只允许一个实心主按钮（见 §12）。

### 8.2 Input

- 高 `32px`，圆角 `--r-2`，描边 `--border-2`，背景 `--surface`，字 `--fs-body`。
- 状态：hover 描边 `--muted`；focus 描边 `--accent` + `box-shadow:0 0 0 3px var(--accent-soft)`（无默认 outline）；error 描边 `--danger` + `--danger-soft` 光环 + 底部错误文案（`--fs-xs`，`--danger`）；disabled 底 `--neutral-soft`、字 `--muted`。
- 配套 `.field`：label（12px/500 text-2）+ 控件 + helper（11px muted）。

### 8.3 Search（人物搜索 + 联想）

- 输入框高 `34px`，圆角 `--r-2`；左侧 15px 搜索图标（muted，绝对定位），右侧清空按钮（hover 显形）。
- 联想下拉 `.suggest`：`--elevated` 底 + `--border` + `--sh-2` + 圆角 `--r-3`，`max-height:330px` 内部滚动，内距 4px。
- 行 `.suggest-row`：姓名 14px/500，命中词高亮 `--accent-strong`；右侧 mono `提及 N`；hover 底 `--neutral-soft` 且显示「设为中心」箭头（accent-strong）。空结果显示引导文案（13px muted）。
- 交互：输入 250ms 防抖联想；点击行＝选中并切换中心人物；Esc / 点击外部关闭；最多展示 8 条。

### 8.4 Card（面板）

- `.panel`：`--surface` 底 + `--border` 描边 + `--r-4` 圆角 + `--sp-4` 内距。
- 不用背景色块堆叠做分区——分区靠发丝线 + 留白（工具类产品语义）。

### 8.5 Badge

- 状态徽标：高 `20px` 胶囊，字 11px/500；底/字成对（见 §4.2 soft 色）。
- `badge-success`（分析完成）、`badge-warning`（分析中/部分完成）、`badge-danger`（分析失败）、`badge-accent`（中心/演示数据）、`badge`（中性）。
- 分析中带 6px 呼吸圆点（`pulse 1.4s` 透明度 1↔0.25）。
- 关系类型徽标 `.rel-badge`：高 `22px`，字 12px/600，含 14×3px 色条 swatch（见 §4.3）。

### 8.6 Progress

- 轨道高 `6px`（大号 `8px`），`--neutral-soft`，胶囊圆角，`overflow:hidden`。
- 填充：成功 `--success`；进行中 `--accent`；失败 `--danger`；宽度过渡 `0.3s`。
- 文案：`N / 1,284 块 · P%`（mono tabular）。

### 8.7 Tooltip

- 深色卡片：底 `oklch(24% .025 250 / .96)`，字 `oklch(96% .005 250)`，圆角 `--r-2`，内距 `8px 10px`，`--sh-2`，`max-width:250px`，`pointer-events:none`。
- 结构：标题（13px/600 白）+ meta 行（mono，`oklch(78% .01 250)`）；关系提示含类型色点 + 类型名 + weight / conf / 证据条数。
- 定位：跟随指针，自动翻转防止溢出视口。

### 8.8 Drawer（上传抽屉）

- 遮罩：全屏 `oklch(24% .025 250 / .32)`，`z-index:120`。
- 面板：右滑，宽 `min(460px,100vw)`，`--surface`，左边框，`--sh-3`，入场 `0.22s` 位移动画。
- 结构：头部（高 52px，标题 16px/600 + 关闭图标按钮，底部发丝线）+ 内容区（`--sp-5` 内距，纵向滚动）。
- 上传交互：dashed 拖放区（hover 描边转 accent，底色 `accent 4%`）→ 文件行（名称 + 大小 + 移除）→「开始分析」主按钮（无文件时 disabled）；非 .epub 显示错误条。

### 8.9 Empty State

- 垂直居中：44px 图标块（`--neutral-soft` 底，SVG）+ 标题（14px/600 `--text-2`）+ 描述（13px muted，`max-width:30ch`）。
- 场景：右侧未选中关系、搜索无结果、孤立人物子图。

### 8.10 Loading State

- 转圈：18px 圆环，`--border-2` 底 + `--accent` 顶部，`0.8s` 旋转。
- 关系图加载遮罩：覆盖画布，`surface 78%` 半透明 + spinner + 文案（切换中心时约 320ms）。
- 骨架屏：`--neutral-soft` 块 + 高光扫过动画（仅用于占位加载）。

### 8.11 Error State

- 错误条：底 `--danger-soft`、边 `color-mix(in oklch, var(--danger) 30%, white)`、字 `--danger`；16px 警告图标 + 标题（600）+ 说明；圆角 `--r-3`。
- 场景：上传格式错误、分析失败（对应 `JobResponse.error` / `failed` 状态）。

---

## 9. Graph Visualization（关系图）

> 数据结构对应（保持 V0.1 API 不变）：`GraphNode{id,name,mention_count,is_center}`、`GraphEdge{source_id,target_id,type,weight,confidence,evidence[]}`、`Evidence{chapter_id,chapter_title,text}`。类型取值：`love / family / friendship / enmity / alliance / mentorship / other`。

### 9.1 画布与布局

- 背景：`--surface` + 点阵网格 `radial-gradient(var(--border) 1px, transparent 1px)`，`22px×22px`。
- 视口：`viewBox="0 0 900 600"`，`preserveAspectRatio="xMidYMid meet"`。
- 布局：同心圆——中心人物在 (450,300)，一跳邻居按角度均匀分布在圆上，半径 `R = min(212, 110 + 邻居数×10)`。
- 缩放：`0.5–2.5`，按钮步进 `×1.25`，「适应」复位 `1`；缩放以画布中心为原点。

### 9.2 节点

| 节点 | 规则 |
|---|---|
| 中心节点 | 半径 20；填充 `--accent`，白色描边 3px，外圈 `--accent-soft` 光晕（r+8）；名称 12.5px/600 `--fg` 置于节点下方（y=r+22） |
| 邻居节点 | 半径 `8 + sqrt(mention_count/982) × 9`（约 8–17px，随提及数缩放）；填充 `--surface`，描边 `--border-2` 1.6px；名称 12.5px/500 `--text-2`（y=r+15） |
| hover | 轻投影（`--sh-1` 级 drop-shadow）；邻居描边转 `--accent` 2.4px；名称转 `--fg` |
| 点击 | 点击邻居＝切换为中心人物（重新加载其 1-hop 子图，约 320ms 加载态）；点击中心无操作 |

- 视觉层级：中心人物 > 一跳邻居 > 关系边，由视觉重量显式表达。

### 9.3 边

- 宽度：`clamp(2.2, 1 + log2(weight+1) × 0.42, 3.4)`；hover / selected 加粗至 4px。
- 颜色 + 线型：见 §4.3（enmity 虚线、mentorship 点线、other 细点线）。
- 命中区：额外 16px 透明描边 `edge-hit` 扩大点击/悬停范围。
- 边标签（`edge-label-pill`）：位于边中点的小胶囊——`--surface` 底 + `--border-2` 1px 描边 + 类型名 11px/600（类型色文字）；hover/选中时描边强调。
- 选中态：该边加粗 + `svg.has-selection` 下其余边降为 `opacity:.32`、其余标签 `opacity:.35`（聚焦当前关系）。

### 9.4 图例（右上浮层）

- `--elevated` 底 + `--border` + `--sh-1` + `--r-3`，`min-width:132px`。
- 标题「关系类型」+ 7 行（22px 色条/线型示例 + 中文类型名），颜色与线型与真实边一致。

### 9.5 交互提示与持久化

- 画布底部居中操作提示 pill：「点击人物切换中心 · 点击连线查看原文证据」。
- 当前中心人物写入 `localStorage`（key `wb-center`），刷新后恢复。

---

## 10. Evidence Panel（右侧关系详情）

- 头部 sticky：「关系详情」+ 关闭按钮（选中时显示）。
- **关系摘要**：左＝源人物名（15px/600，`max-width:140px` 超长省略）+ mono `提及 N`；中＝关系类型 badge；右＝目标人物名（右对齐）。
- **Meta 网格**（2 列 × 2 行，`--surface` 卡 + `--border` + `--r-3`）：
  - 关系类型（中文名 600）
  - 置信度：百分比（mono）+ 5 段置信度条（`--success` 填充）
  - 权重（mono）
  - 证据条数（mono）
- **原文证据列表**：标题「原文证据」+ 条数（mono）；每条：
  - 章节引用：`第 N 章`（mono/600 text-2）+ 章回名（12px muted）
  - 原文块：14.5px / 行高 1.85 / `--fg`，内距 12px/16px，`--neutral-soft` 底 + `--border` 描边 + `--r-3`，适合长文精读
  - 条目间以发丝线分隔（不用左侧色条 callout 样式）
- 未选中时显示空状态（见 §8.9）。

---

## 11. States（状态汇总）

| 状态 | 规则 |
|---|---|
| loading | 转圈 spinner / 画布半透明遮罩 / 骨架屏；时长约 320ms（切中心） |
| empty | 图标 + 标题 + 引导文案；右侧未选关系、搜索无结果、孤立人物 |
| error | danger 错误条（上传格式、分析失败）；`JobResponse.failed` 对应顶栏 `badge-danger` |
| success | `badge-success` + 绿色进度填充；分析完成 toast |
| hover | 前景对比度只升不降；按钮/节点/边/链接均有明确 hover 态（见 §8、§9） |
| focus | 所有可聚焦元素 `:focus-visible` 焦点环（2px accent + 2px offset） |
| disabled | `opacity:.45; cursor:not-allowed`，唯一允许降对比度 |
| selected | 选中关系边加粗并聚焦（其余边淡化）；详情面板联动 |

**任务状态机映射**（与 `JobResponse.status` 一一对应）：

| status | 视觉 |
|---|---|
| `pending` | 中性 badge「等待中」 |
| `running` | warning badge + 呼吸点「分析中」+ 进度条（accent 填充） |
| `completed` | success badge「分析完成」+ 统计展示 |
| `completed_with_errors` | warning badge「部分完成」+ 失败块提示 |
| `failed` | danger badge「分析失败」+ error-banner（展示 `error` 文案） |

---

## 12. Forbidden Patterns（明确禁止）

- ❌ 大面积渐变背景（含紫色渐变）；仅允许点阵网格纹理与骨架扫光这类功能性图案。
- ❌ 玻璃拟态（无 frosted-glass 卡片；顶栏/浮层用实色 + 发丝线）。
- ❌ 大量 Glow / 发光效果；中心节点仅允许低透明度柔和外环，无霓虹光晕。
- ❌ 过度圆角（卡片不超过 `--r-4`）。
- ❌ Chat UI / 气泡式对话界面；本产品是分析工作台，无聊天机器人模块。
- ❌ SaaS Landing Page 风格（无巨大 Hero、无营销插画、无标语式文案）。
- ❌ 不必要的装饰与动画；动效仅限状态过渡（≤0.3s）与加载反馈。
- ❌ emoji 作为功能图标（一律内联 SVG monoline）。
- ❌ 同一视口内多个实心主按钮（同一动作只保留一个 primary，其余用 secondary/ghost/文字链接）。
- ❌ 为设计师/演示者存在的控制面板与演示开关。
- ❌ 散落魔数：颜色/间距/圆角/阴影必须使用本文件记录的 Token。
- ❌ 新增业务功能与模块（保持 V0.1 的 API、数据结构、业务流程不变）。

---

*本文档由已验收的 `design-system.html` 与 `novel-graph-workbench.html` 直接提炼生成，未引入任何新设计决策。*
