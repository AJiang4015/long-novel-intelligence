/** EmptyState.tsx —— 通用空状态展示（图标块 + 标题 + 引导文案） */
import type { ReactNode } from "react";

interface EmptyStateProps {
  /** 44px 图标块内容（建议传入 icons.tsx 的图标组件） */
  icon?: ReactNode;
  title: string;
  description?: string;
}

/** 空状态：图标块 + 标题 + 引导文案（.empty 结构） */
export default function EmptyState({ icon, title, description }: EmptyStateProps) {
  return (
    <div className="empty">
      {icon && <div className="empty-icon">{icon}</div>}
      <span className="empty-title">{title}</span>
      {description && <p className="empty-desc">{description}</p>}
    </div>
  );
}
