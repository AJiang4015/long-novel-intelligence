interface ToastProps {
  message: string | null;
  /** info = 强调色圆点（如切换中心）；success = 绿色圆点（默认） */
  kind?: "info" | "success";
}

/** 底部居中的轻提示（.toast 结构）；message 为 null 时不渲染 */
export default function Toast({ message, kind = "success" }: ToastProps) {
  if (!message) return null;
  return (
    <div className={kind === "info" ? "toast is-info" : "toast"} role="status">
      <span className="toast-dot" />
      <span>{message}</span>
    </div>
  );
}
