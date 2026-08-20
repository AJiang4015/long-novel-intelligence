import { useEffect, useMemo, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { getGraph } from "../api";
import { toForceGraph } from "../types";
import type { Evidence, ForceLink, ForceNode, GraphResponse } from "../types";

interface Props {
  characterId: string;
  onCenterChange: (id: string) => void;
}

const TYPE_COLORS: Record<string, string> = {
  love: "#e91e63",
  family: "#9c27b0",
  friendship: "#2196f3",
  enmity: "#f44336",
  alliance: "#4caf50",
  mentorship: "#ff9800",
  other: "#9e9e9e",
};

export default function GraphView({ characterId, onCenterChange }: Props) {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<ForceLink | null>(null);

  useEffect(() => {
    let cancelled = false;
    getGraph(characterId).then((g) => {
      if (!cancelled) {
        setGraph(g);
        setSelectedEdge(null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [characterId]);

  const data = useMemo(() => (graph ? toForceGraph(graph) : null), [graph]);

  if (!data) return <p>加载关系图…</p>;

  return (
    <div style={{ display: "flex", height: 600 }}>
      <div style={{ flex: 1 }}>
        <ForceGraph2D
          graphData={{ nodes: data.nodes, links: data.links }}
          nodeId="id"
          nodeLabel={(n: ForceNode) => `${n.name}（${n.mention_count} 块）`}
          nodeVal={(n: ForceNode) => Math.max(3, Math.log2(n.mention_count + 1) * 4)}
          nodeColor={(n: ForceNode) => (n.isCenter ? "#ff5722" : "#607d8b")}
          linkColor={(l: ForceLink) => TYPE_COLORS[l.type] ?? "#999"}
          linkWidth={(l: ForceLink) => Math.min(6, 1 + Math.log2(l.weight + 1))}
          onNodeClick={(n: ForceNode) => {
            if (!n.isCenter) onCenterChange(n.id);
          }}
          onLinkClick={(l: ForceLink) => setSelectedEdge(l)}
        />
      </div>
      {selectedEdge && (
        <div style={{ width: 300, padding: 8, overflow: "auto", borderLeft: "1px solid #ccc" }}>
          <h4>
            {selectedEdge.type} · weight {selectedEdge.weight} · 置信度{" "}
            {selectedEdge.confidence.toFixed(2)}
          </h4>
          {selectedEdge.evidence.map((e: Evidence, i: number) => (
            <div key={i} style={{ marginBottom: 8, fontSize: 13 }}>
              <strong>
                第{e.chapter_id}章 {e.chapter_title}
              </strong>
              <p style={{ whiteSpace: "pre-wrap", maxHeight: 120, overflow: "auto" }}>{e.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
