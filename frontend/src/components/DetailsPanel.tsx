/**
 * DetailsPanel —— 右侧关系详情：关系摘要 + meta 网格 + 原文证据 + 空态。
 * 结构逐字参照 workbench selectEdge 生成的 DOM（.rel-summary / .meta-grid / .ev-head / .evidence-item）。
 * 人物名由 graph.nodes 按 source_id / target_id 解析；无硬编码色值。
 */
import type { GraphEdge, GraphResponse } from "../types";
import EmptyState from "./EmptyState";
import { CloseIcon, GraphNodesIcon } from "./icons";

interface DetailsPanelProps {
  graph: GraphResponse | null; // 用于由 source_id/target_id 解析人物名
  selectedEdge: GraphEdge | null;
  onClose: () => void;
}

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

/** 千分位（spec §5：en-US 恒定逗号） */
const fmt = (n: number) => n.toLocaleString("en-US");

function nodeName(graph: GraphResponse | null, id: string): string {
  return graph?.nodes.find((n) => n.id === id)?.name ?? id;
}

function nodeMention(graph: GraphResponse | null, id: string): number {
  return graph?.nodes.find((n) => n.id === id)?.mention_count ?? 0;
}

export default function DetailsPanel({ graph, selectedEdge, onClose }: DetailsPanelProps) {
  if (!selectedEdge) {
    return (
      <>
        <div className="right-head">
          <span className="section-title">关系详情</span>
        </div>
        <div className="right-body">
          <EmptyState
            icon={<GraphNodesIcon />}
            title="未选择关系"
            description="点击关系图中的任意连线，查看关系详情与原文证据。"
          />
        </div>
      </>
    );
  }

  const edge = selectedEdge;
  const conf = Math.round(edge.confidence * 100);
  const meter = [10, 30, 50, 70, 90].map((t) => (
    <i key={t} className={conf >= t ? "on" : ""} />
  ));

  return (
    <>
      <div className="right-head">
        <span className="section-title">关系详情</span>
        <button
          type="button"
          className="btn btn-icon"
          aria-label="关闭详情"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </div>
      <div className="right-body">
        <div className="rel-summary">
          <div className="rs-endpoint">
            <span className="rs-name">{nodeName(graph, edge.source_id)}</span>
            <span className="rs-sub">{fmt(nodeMention(graph, edge.source_id))} 提及</span>
          </div>
          <span className="rel-badge" data-type={edge.type}>
            <span className="swatch" data-type={edge.type} />
            {TYPE_LABEL[edge.type] ?? edge.type}
          </span>
          <div className="rs-endpoint" style={{ textAlign: "right" }}>
            <span className="rs-name">{nodeName(graph, edge.target_id)}</span>
            <span className="rs-sub">{fmt(nodeMention(graph, edge.target_id))} 提及</span>
          </div>
        </div>

        <div className="meta-grid">
          <div className="meta-cell">
            <span className="mc-label">关系类型</span>
            <span
              className="mc-value"
              style={{ fontFamily: "var(--font-body)", fontWeight: 600 }}
            >
              {TYPE_LABEL[edge.type] ?? edge.type}
            </span>
          </div>
          <div className="meta-cell">
            <span className="mc-label">置信度</span>
            <span className="mc-value">
              <span className="num">{(edge.confidence * 100).toFixed(0)}</span>
              <span className="mc-unit">%</span>
              <span className="conf-meter">{meter}</span>
            </span>
          </div>
          <div className="meta-cell">
            <span className="mc-label">权重</span>
            <span className="mc-value num">{edge.weight}</span>
          </div>
          <div className="meta-cell">
            <span className="mc-label">证据</span>
            <span className="mc-value">
              <span className="num">{edge.evidence.length}</span>
              <span className="mc-unit"> 条</span>
            </span>
          </div>
        </div>

        <div>
          <div className="ev-head">
            <span className="section-title">原文证据</span>
            <span className="ev-count num">{edge.evidence.length} 条</span>
          </div>
          <div style={{ marginTop: 4 }}>
            {edge.evidence.map((ev) => (
              <div className="evidence-item" key={ev.chunk_id}>
                <div className="evidence-ref">
                  <span className="chapter-no">第 {ev.chapter_id} 章</span>
                  <span>{ev.chapter_title}</span>
                </div>
                <p className="evidence-text">{ev.text}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
