/**
 * GraphLegend —— 右上图例浮层（workbench .graph-legend 结构）。
 * 颜色与线型与真实边一致；禁止硬编码色值，一律 var(--rel-*)。
 * enmity 虚线 / mentorship 点线 / other 细点线（参照 workbench 内联 style 写法）。
 */
import type { CSSProperties } from "react";

interface LegendRow {
  label: string;
  style: CSSProperties;
}

const ROWS: LegendRow[] = [
  { label: "爱恋", style: { background: "var(--rel-love)" } },
  { label: "家族", style: { background: "var(--rel-family)" } },
  { label: "友谊", style: { background: "var(--rel-friendship)" } },
  {
    label: "敌对",
    style: {
      background: "var(--rel-enmity)",
      border: "1px dashed var(--rel-enmity)",
      height: 0,
    },
  },
  { label: "同盟", style: { background: "var(--rel-alliance)" } },
  {
    label: "师承",
    style: {
      background: "var(--rel-mentorship)",
      height: 0,
      borderTop: "2px dotted var(--rel-mentorship)",
    },
  },
  {
    label: "其他",
    style: {
      background: "var(--rel-other)",
      height: 0,
      borderTop: "1.5px dotted var(--rel-other)",
    },
  },
];

export default function GraphLegend() {
  return (
    <div className="graph-legend">
      <span className="lg-title">关系类型</span>
      {ROWS.map((row) => (
        <div className="lg-row" key={row.label}>
          <span className="lg-line" style={row.style} />
          {row.label}
        </div>
      ))}
    </div>
  );
}
