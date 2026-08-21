import { WarningIcon } from "./icons";

interface ErrorBannerProps {
  title: string;
  detail?: string;
}

/** 错误条：16px 警告图标 + 标题（600）+ 说明（.error-banner 结构） */
export default function ErrorBanner({ title, detail }: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <WarningIcon size={16} />
      <div>
        <strong>{title}</strong>
        {detail && <div style={{ marginTop: 2 }}>{detail}</div>}
      </div>
    </div>
  );
}
