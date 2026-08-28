# Frontend（长篇小说人物关系图谱可视化）

React + TypeScript + Vite。

- 入口 `src/App.tsx`：上传 → 后台分析（job 轮询）→ 图展示 的阶段机
- `src/api.ts`：后端 REST 封装
- `src/components/GraphCanvas.tsx`：自绘 SVG 人物关系图

```bash
npm install
npm run dev     # http://localhost:5173（Vite dev proxy 转发 /api 到后端）
```
