/**
 * GraphPanel —— 中央容器：toolbar + GraphCanvas + legend + 加载/处理遮罩 + hint。
 * 结构参照 workbench 中央区（.graph-toolbar / .graph-canvas / 浮层）。
 * 类名与 workbench 逐字一致；组件内无硬编码色值。
 */
import { useRef } from "react";
import type {
  CharacterCandidate,
  GraphEdge,
  GraphResponse,
  JobResponse,
} from "../types";
import GraphCanvas, { type GraphCanvasHandle } from "./GraphCanvas";
import GraphLegend from "./GraphLegend";
import { DocIcon, FitIcon, GraphNodesIcon, MinusIcon, PlusIcon } from "./icons";
import Spinner from "./Spinner";

interface GraphPanelProps {
  graph: GraphResponse | null;
  center: CharacterCandidate | null;
  selectedEdge: GraphEdge | null;
  graphLoading: boolean; // 切换中心真实加载中
  processing: boolean; // 整本分析进行中
  job: JobResponse | null; // 处理遮罩进度用
  novelTitle?: string; // 处理遮罩「正在分析《书名》」
  onNodeClick: (id: string) => void;
  onEdgeClick: (edge: GraphEdge) => void;
}

/** 千分位（spec §5：en-US 恒定逗号） */
const fmt = (n: number) => n.toLocaleString("en-US");

export default function GraphPanel({
  graph,
  center,
  selectedEdge,
  graphLoading,
  processing,
  job,
  novelTitle,
  onNodeClick,
  onEdgeClick,
}: GraphPanelProps) {
  const canvasRef = useRef<GraphCanvasHandle>(null);

  const done = job?.progress.done_chunks ?? 0;
  const total = job?.progress.total_chunks ?? 0;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <>
      <div className="graph-toolbar">
        <div className="gt-left">
          <span className="gt-label">中心人物</span>
          <span className="gt-center-name">{center?.name ?? ""}</span>
          {center && (
            <span className="badge">
              <span className="num">{fmt(center.mention_count)}</span> 提及
            </span>
          )}
          {graph && (
            <span className="badge">{graph.nodes.length > 1 ? "1-hop" : "孤立"}</span>
          )}
        </div>
        <div className="gt-right">
          <button
            type="button"
            className="btn btn-icon"
            aria-label="放大"
            onClick={() => canvasRef.current?.zoomIn()}
          >
            <PlusIcon />
          </button>
          <button
            type="button"
            className="btn btn-icon"
            aria-label="缩小"
            onClick={() => canvasRef.current?.zoomOut()}
          >
            <MinusIcon />
          </button>
          <button
            type="button"
            className="btn btn-icon"
            aria-label="适应视图"
            onClick={() => canvasRef.current?.fit()}
          >
            <FitIcon />
          </button>
        </div>
      </div>

      <div className="graph-canvas">
        {graph && center ? (
          <GraphCanvas
            ref={canvasRef}
            graph={graph}
            centerId={center.id}
            selectedEdge={selectedEdge}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
          />
        ) : (
          <div className="empty" style={{ position: "absolute", inset: 0 }}>
            <div className="empty-icon">
              <GraphNodesIcon />
            </div>
            <span className="empty-title">选择人物</span>
            <p className="empty-desc">从左侧搜索并选择一个人物，查看其 1-hop 关系网络。</p>
          </div>
        )}

        <GraphLegend />

        {graphLoading && (
          <div className="graph-loading">
            <Spinner />
            <span>正在加载子图…</span>
          </div>
        )}

        {processing && (
          <div className="graph-processing">
            <span style={{ color: "var(--accent)" }}>
              <DocIcon size={40} />
            </span>
            <span className="gp-title">
              {novelTitle ? `正在分析《${novelTitle}》` : "正在分析…"}
            </span>
            <div className="gp-bar">
              <div className="progress progress-lg">
                <div
                  className="progress-fill is-running"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
            <span className="gp-nums">
              {fmt(done)} / {fmt(total)} 块 · {pct}%
            </span>
            <span className="gp-caption">切块 → 并发抽取人物与关系 → 聚合写入图谱</span>
          </div>
        )}

        <div className="graph-hint">
          <span>点击人物切换中心</span>
          <span className="hint-sep" />
          <span>点击连线查看原文证据</span>
        </div>
      </div>
    </>
  );
}
