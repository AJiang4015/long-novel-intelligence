/**
 * GraphCanvas —— 受控纯 UI 组件（spec §4）。
 * 数据全部由父级传入；内部仅负责 SVG 布局/渲染、缩放（按钮 0.5–2.5 ×1.25 + 适应）、
 * 基础鼠标拖拽平移、hover tooltip、edge hit area 与点击回调。
 * 布局数学与类名逐字参照 design/novel-graph-workbench.html 的
 * renderGraph / applyZoom / moveTooltip / selectEdge。
 * 组件内不出现任何硬编码色值（一律 var(--*)）。
 */
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import type { GraphEdge, GraphNode, GraphResponse } from "../types";

export interface GraphCanvasHandle {
  zoomIn(): void;
  zoomOut(): void;
  fit(): void;
}

interface GraphCanvasProps {
  graph: GraphResponse; // 唯一图数据来源（App 传入）
  centerId: string;
  selectedEdge: GraphEdge | null; // 选中边（App 持有）
  onNodeClick: (id: string) => void; // 点击邻居 → 切换中心（App 处理）
  onEdgeClick: (edge: GraphEdge) => void; // 点击边 → 选中（App 处理）
}

const CX = 450;
const CY = 300;
const CENTER_R = 20;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 1.25;
const MAX_MENTION = 982; // 邻居半径归一化基准（workbench 演示数据最大值）

/** 类型中文映射（workbench TYPE_LABEL） */
const TYPE_LABEL: Record<string, string> = {
  love: "爱恋",
  family: "家族",
  friendship: "友谊",
  enmity: "敌对",
  alliance: "同盟",
  mentorship: "师承",
  other: "其他",
};

/** 千分位（spec §5：en-US 恒定逗号，禁止空格） */
const fmt = (n: number) => n.toLocaleString("en-US");

function edgeKey(e: GraphEdge): string {
  return `${e.source_id}__${e.target_id}__${e.type}`;
}

/** 节点半径：中心 20；邻居 round(8 + sqrt(mention_count/982)*9) */
function nodeRadius(node: GraphNode | undefined, centerId: string): number {
  if (!node || node.id === centerId) return CENTER_R;
  return Math.round(8 + Math.sqrt(node.mention_count / MAX_MENTION) * 9);
}

/** 边宽：clamp(2.2, 1 + log2(weight+1)*0.42, 3.4) */
function edgeStrokeWidth(e: GraphEdge): number {
  return Math.min(3.4, Math.max(2.2, 1 + Math.log2(e.weight + 1) * 0.42));
}

/** 按端点半径缩短连线（workbench shorten） */
function shorten(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  ra: number,
  rb: number,
): [number, number, number, number] {
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  return [ax + ux * ra, ay + uy * ra, bx - ux * rb, by - uy * rb];
}

const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(
  function GraphCanvas(
    { graph, centerId, selectedEdge, onNodeClick, onEdgeClick },
    ref,
  ) {
    const [zoom, setZoom] = useState(1);
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const [hoveredKey, setHoveredKey] = useState<string | null>(null);
    const [tooltip, setTooltip] = useState<{
      content: ReactNode;
      x: number;
      y: number;
    } | null>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);

    /* 基础拖拽平移：pointerdown 记起点，window pointermove/pointerup 收尾 */
    const [dragging, setDragging] = useState(false);
    const dragRef = useRef<{
      startX: number;
      startY: number;
      baseX: number;
      baseY: number;
    } | null>(null);
    const didDragRef = useRef(false);

    /* 布局：中心 (450,300)；邻居角度 -π/2 + (i/n)×2π，R = min(212, 110 + n×10) */
    const layout = useMemo(() => {
      const center = graph.nodes.find((n) => n.id === centerId);
      const nbrs = graph.nodes.filter((n) => n.id !== centerId);
      const R = Math.min(212, 110 + nbrs.length * 10);
      const pos = new Map<string, { x: number; y: number }>();
      nbrs.forEach((n, i) => {
        const angle = -Math.PI / 2 + (i / nbrs.length) * Math.PI * 2;
        pos.set(n.id, { x: CX + Math.cos(angle) * R, y: CY + Math.sin(angle) * R });
      });
      if (center) pos.set(center.id, { x: CX, y: CY });
      return { center, nbrs, pos };
    }, [graph, centerId]);

    /* 边 key → GraphEdge 缓存（点击/悬停按 data-edge-key 匹配） */
    const edgeByKey = useMemo(() => {
      const m = new Map<string, GraphEdge>();
      graph.edges.forEach((e) => m.set(edgeKey(e), e));
      return m;
    }, [graph]);

    const isolated = graph.nodes.length <= 1;

    /* 缩放按钮句柄（clamp [0.5, 2.5]，×1.25 / 适应复位） */
    useImperativeHandle(
      ref,
      () => ({
        zoomIn: () => setZoom((z) => Math.min(MAX_ZOOM, z * ZOOM_STEP)),
        zoomOut: () => setZoom((z) => Math.max(MIN_ZOOM, z / ZOOM_STEP)),
        fit: () => setZoom(1),
      }),
      [],
    );

    /* tooltip 防溢出翻转（workbench moveTooltip 逐字） */
    function moveTooltip(x: number, y: number) {
      const el = tooltipRef.current;
      if (!el) return;
      const pad = 14;
      const tw = el.offsetWidth;
      const th = el.offsetHeight;
      let tx = x;
      let ty = y - th - 12;
      if (tx + tw / 2 > window.innerWidth - pad) tx = window.innerWidth - pad - tw / 2;
      if (tx - tw / 2 < pad) tx = pad + tw / 2;
      if (ty < pad) ty = y + 18;
      el.style.left = `${tx}px`;
      el.style.top = `${ty}px`;
    }

    useEffect(() => {
      if (tooltip) moveTooltip(tooltip.x, tooltip.y);
    }, [tooltip]);

    /* 拖拽：window 级监听，避免指针移出 svg 后丢失 */
    useEffect(() => {
      if (!dragging) return;
      const onMove = (ev: PointerEvent) => {
        const d = dragRef.current;
        if (!d) return;
        const dx = ev.clientX - d.startX;
        const dy = ev.clientY - d.startY;
        if (Math.abs(dx) + Math.abs(dy) > 3) didDragRef.current = true;
        if (didDragRef.current) setPan({ x: d.baseX + dx, y: d.baseY + dy });
      };
      const onUp = () => {
        dragRef.current = null;
        setDragging(false);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      return () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
    }, [dragging]);

    function handlePointerDown(e: ReactPointerEvent<SVGSVGElement>) {
      didDragRef.current = false;
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        baseX: pan.x,
        baseY: pan.y,
      };
      setDragging(true);
    }

    function handleMouseOver(e: ReactMouseEvent<SVGSVGElement>) {
      const target = e.target as Element;
      const nEl = target.closest(".graph-node");
      const eEl = target.closest(".graph-edge, .edge-hit");
      if (nEl && !nEl.classList.contains("is-center")) {
        const id = nEl.getAttribute("data-id");
        const node = graph.nodes.find((n) => n.id === id);
        if (node) {
          setTooltip({
            content: (
              <>
                <span className="tt-title">{node.name}</span>
                <div className="tt-meta">
                  <span>提及 {fmt(node.mention_count)} 块</span>
                  <span>1-hop</span>
                </div>
              </>
            ),
            x: e.clientX,
            y: e.clientY,
          });
        }
      } else if (eEl) {
        const key = eEl.getAttribute("data-edge-key");
        const ed = key ? edgeByKey.get(key) : undefined;
        if (ed) {
          const a = graph.nodes.find((n) => n.id === ed.source_id);
          const b = graph.nodes.find((n) => n.id === ed.target_id);
          setTooltip({
            content: (
              <>
                <span className="tt-title">
                  {a?.name ?? ed.source_id} → {b?.name ?? ed.target_id}
                </span>
                <div className="tt-edge">
                  <span
                    className="tt-dot"
                    style={{ background: `var(--rel-${ed.type})` }}
                  />
                  {TYPE_LABEL[ed.type] ?? ed.type}
                </div>
                <div className="tt-meta">
                  <span>weight {ed.weight}</span>
                  <span>conf {ed.confidence.toFixed(2)}</span>
                  <span>证据 {ed.evidence.length} 条</span>
                </div>
              </>
            ),
            x: e.clientX,
            y: e.clientY,
          });
        } else {
          setTooltip(null);
        }
      } else {
        setTooltip(null);
      }
    }

    function handleMouseMove(e: ReactMouseEvent<SVGSVGElement>) {
      if (tooltip) moveTooltip(e.clientX, e.clientY);
    }

    function handleClick(e: ReactMouseEvent<SVGSVGElement>) {
      /* 拖拽后抑制 click，避免误触 */
      if (didDragRef.current) {
        didDragRef.current = false;
        return;
      }
      const target = e.target as Element;
      const nEl = target.closest(".graph-node");
      const eEl = target.closest(".graph-edge, .edge-hit");
      if (nEl) {
        const id = nEl.getAttribute("data-id");
        if (id && id !== centerId) onNodeClick(id);
      } else if (eEl) {
        const key = eEl.getAttribute("data-edge-key");
        const edge = key ? edgeByKey.get(key) : undefined;
        if (edge) onEdgeClick(edge);
      }
      /* 空白 → 无操作（选中态由父级管理） */
    }

    const selectedKey = selectedEdge ? edgeKey(selectedEdge) : null;
    const rootTransform = `translate(${CX + pan.x} ${CY + pan.y}) scale(${zoom}) translate(${-CX} ${-CY})`;

    /* 边（先画，节点覆盖其上）：edge-hit → graph-edge → edge-label-pill */
    const edgeEls = graph.edges.map((e) => {
      const a = layout.pos.get(e.source_id);
      const b = layout.pos.get(e.target_id);
      if (!a || !b) return null;
      const key = edgeKey(e);
      const ra = nodeRadius(
        graph.nodes.find((n) => n.id === e.source_id),
        centerId,
      );
      const rb = nodeRadius(
        graph.nodes.find((n) => n.id === e.target_id),
        centerId,
      );
      const [x1, y1, x2, y2] = shorten(a.x, a.y, b.x, b.y, ra, rb);
      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2;
      const label = TYPE_LABEL[e.type] ?? e.type;
      const lw = label.length * 12 + 18;
      const lh = 19;
      const isSelected = key === selectedKey;
      const strokeW = isSelected || key === hoveredKey ? 4 : edgeStrokeWidth(e);
      return (
        <g
          className="edge-wrap"
          key={key}
          onMouseEnter={() => setHoveredKey(key)}
          onMouseLeave={() => setHoveredKey((k) => (k === key ? null : k))}
        >
          <path
            className="edge-hit"
            data-edge-key={key}
            d={`M${x1},${y1} L${x2},${y2}`}
          />
          <path
            className={`graph-edge edge-${e.type}${isSelected ? " is-selected" : ""}`}
            data-edge-key={key}
            d={`M${x1},${y1} L${x2},${y2}`}
            style={{ strokeWidth: strokeW }}
          />
          <g
            className={`edge-label-pill is-${e.type}${isSelected ? " is-selected" : ""}`}
            transform={`translate(${mx - lw / 2}, ${my - lh / 2})`}
          >
            <rect width={lw} height={lh} rx={9.5} />
            <text x={lw / 2} y={lh / 2 + 4} textAnchor="middle">
              {label}
            </text>
          </g>
        </g>
      );
    });

    /* 邻居节点：surface 填充 + border-2 描边，半径随提及数 */
    const nbrEls = layout.nbrs.map((n) => {
      const p = layout.pos.get(n.id);
      if (!p) return null;
      const r = nodeRadius(n, centerId);
      return (
        <g
          className="graph-node"
          key={n.id}
          data-id={n.id}
          transform={`translate(${p.x},${p.y})`}
        >
          <circle
            className="node-core"
            r={r}
            fill="var(--surface)"
            stroke="var(--border-2)"
            strokeWidth={1.6}
          />
          <text className="node-label" y={r + 15} textAnchor="middle">
            {n.name}
          </text>
        </g>
      );
    });

    /* 中心节点：accent-soft 外环 + accent 填充 + 白描边 */
    const centerEl = layout.center ? (
      <g
        className="graph-node is-center"
        data-id={layout.center.id}
        transform={`translate(${CX},${CY})`}
      >
        <circle className="node-core" r={CENTER_R + 8} fill="var(--accent-soft)" />
        <circle className="node-core" r={CENTER_R} fill="var(--accent)" />
        <circle
          className="node-core"
          r={CENTER_R}
          fill="none"
          stroke="var(--surface)"
          strokeWidth={3}
        />
        <text className="node-label" y={CENTER_R + 22} textAnchor="middle">
          {layout.center.name}
        </text>
      </g>
    ) : null;

    return (
      <>
        <svg
          className={selectedEdge ? "has-selection" : undefined}
          viewBox="0 0 900 600"
          preserveAspectRatio="xMidYMid meet"
          aria-label="人物一跳关系图"
          onPointerDown={handlePointerDown}
          onMouseOver={handleMouseOver}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setTooltip(null)}
          onClick={handleClick}
        >
          <g id="graphRoot" transform={rootTransform}>
            {!isolated && edgeEls}
            {!isolated && nbrEls}
            {!isolated && centerEl}
          </g>
        </svg>
        {isolated && (
          <div className="empty" style={{ position: "absolute", inset: 0 }}>
            <span className="empty-title">孤立人物</span>
            <p className="empty-desc">该人物没有一跳关系</p>
          </div>
        )}
        {tooltip && (
          <div className="tooltip" ref={tooltipRef}>
            {tooltip.content}
          </div>
        )}
      </>
    );
  },
);

export default GraphCanvas;
