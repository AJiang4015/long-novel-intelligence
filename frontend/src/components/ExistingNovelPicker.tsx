/**
 * 已有小说选择器（多本恢复场景）：极简——只展示小说列表与选择操作（spec 约束 3）。
 * 复用 UploadDrawer 的 drawer 视觉结构（.drawer-overlay/.drawer/.drawer-head/.drawer-body）；
 * 只渲染与回调，不承担任何业务逻辑（UploadDrawer 本体不动）。
 */
import type { NovelListItem } from "../types";
import { ArrowRightIcon, CloseIcon } from "./icons";

interface ExistingNovelPickerProps {
  open: boolean;
  novels: NovelListItem[];
  onClose: () => void;
  onSelect: (novel: NovelListItem) => void;
}

export default function ExistingNovelPicker({
  open,
  novels,
  onClose,
  onSelect,
}: ExistingNovelPickerProps) {
  if (!open) return null;

  return (
    <div
      className="drawer-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="drawer" role="dialog" aria-modal="true" aria-label="选择已有小说">
        <div className="drawer-head">
          <h3>选择已有小说</h3>
          <button className="btn btn-icon" aria-label="关闭" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div className="drawer-body">
          {novels.length === 0 ? (
            <div className="empty">
              <div className="empty-title">没有已分析的小说</div>
              <p className="empty-desc">关闭本面板后，可点击顶部「上传新小说」开始分析。</p>
            </div>
          ) : (
            novels.map((n) => (
              <button key={n.id} className="suggest-row" onClick={() => onSelect(n)}>
                <span className="sr-name">{n.title}</span>
                <span className="sr-meta">
                  <span className="sr-arrow">
                    <ArrowRightIcon size={14} />
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
