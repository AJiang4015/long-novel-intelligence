/**
 * 顶栏：品牌 + 当前小说 chip（状态 badge）+ 设计系统链接 + 上传按钮。
 * 结构与类名逐字取自 design/novel-graph-workbench.html 的 .topbar（唯一事实来源）。
 */
import type { JobStatus } from "../types";
import { BrandGlyph } from "./icons";

interface TopbarProps {
  novelTitle: string | null; // null = 未上传小说
  status: JobStatus | null; // 来自 JobResponse.status；null = 无任务
  onUploadClick: () => void;
}

/** JobStatus → badge 类名与文案（类名逐字取自 workbench 状态切换） */
const STATUS_BADGE: Record<JobStatus, { cls: string; label: string }> = {
  pending: { cls: "badge", label: "等待中" },
  running: { cls: "badge badge-warning badge-running", label: "分析中" },
  completed: { cls: "badge badge-success", label: "分析完成" },
  completed_with_errors: { cls: "badge badge-warning", label: "部分完成" },
  failed: { cls: "badge badge-danger", label: "分析失败" },
};

export default function Topbar({ novelTitle, status, onUploadClick }: TopbarProps) {
  const badge = status ? STATUS_BADGE[status] : { cls: "badge", label: "未上传" };
  return (
    <header className="topbar">
      <span className="brand">
        <span className="brand-glyph">
          <BrandGlyph />
        </span>
        人物关系图谱
        <span className="brand-sub">GRAPH WORKBENCH</span>
      </span>
      <span className="topbar-sep"></span>
      <div className="novel-chip">
        <span className="nc-label">当前小说</span>
        <span className="nc-title">{novelTitle ?? "未选择"}</span>
        <span className={badge.cls}>
          <span className="dot"></span>
          {badge.label}
        </span>
      </div>
      <div className="topbar-actions">
        <a className="link-ds" href="/design-system.html">
          设计系统
        </a>
        <button type="button" className="btn btn-primary" onClick={onUploadClick}>
          上传新小说
        </button>
      </div>
    </header>
  );
}
