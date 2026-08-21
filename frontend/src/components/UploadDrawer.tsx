/**
 * 上传抽屉：dropzone（拖拽/点击选择）+ 文件行 + 错误条 + 开始分析。
 * 结构与类名逐字取自 design/novel-graph-workbench.html 的 #uploadOverlay（唯一事实来源）；
 * 校验/提交逻辑复用现有 Upload.tsx（非 .epub → 错误条；uploadNovel 提交）。
 */
import { useEffect, useRef, useState } from "react";
import { uploadNovel } from "../api";
import ErrorBanner from "./ErrorBanner";
import { CloseIcon, DocIcon, UploadIcon } from "./icons";

interface UploadDrawerProps {
  open: boolean;
  onClose: () => void;
  onUploaded: (novelId: string, jobId: string) => void;
}

interface DrawerError {
  title: string;
  detail?: string;
}

export default function UploadDrawer({ open, onClose, onUploaded }: UploadDrawerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<DrawerError | null>(null);
  const [busy, setBusy] = useState(false);

  // 关闭时重置文件与错误
  useEffect(() => {
    if (!open) {
      setFile(null);
      setError(null);
      setBusy(false);
    }
  }, [open]);

  if (!open) return null;

  /** 校验并接收文件（逻辑对齐 Upload.tsx：非 .epub 拒绝；另处理空文件） */
  function pick(f: File | null | undefined) {
    if (busy || !f) return;
    setError(null);
    if (f.size === 0) {
      setError({ title: "文件为空", detail: "请重新选择文件。" });
      setFile(null);
      return;
    }
    if (!f.name.toLowerCase().endsWith(".epub")) {
      setError({ title: "文件格式不支持", detail: "仅支持 .epub 文件。" });
      setFile(null);
      return;
    }
    setFile(f);
  }

  function remove() {
    setFile(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function start() {
    if (!file || busy) return;
    setBusy(true);
    try {
      const { novel_id, job_id } = await uploadNovel(file);
      onUploaded(novel_id, job_id); // 成功后由父级关闭抽屉
    } catch (e) {
      setError({ title: "上传失败", detail: e instanceof Error ? e.message : "未知错误" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="drawer-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose(); // 点击遮罩关闭
      }}
    >
      <div className="drawer" role="dialog" aria-modal="true" aria-label="上传新小说">
        <div className="drawer-head">
          <h3>上传新小说</h3>
          <button type="button" className="btn btn-icon" aria-label="关闭" onClick={onClose} disabled={busy}>
            <CloseIcon />
          </button>
        </div>
        <div className="drawer-body">
          <div
            className="dropzone"
            tabIndex={0}
            role="button"
            aria-label="选择或拖拽 epub 文件"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pick(e.dataTransfer.files?.[0]);
            }}
          >
            <UploadIcon size={26} style={{ color: "var(--muted)" }} />
            <div className="dz-title">
              拖拽 .epub 文件到此处，或<span className="dz-link">点击选择文件</span>
            </div>
            <div className="dz-hint">支持 .epub · 最大 50MB · 上传后自动开始分析</div>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".epub"
            hidden
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {file && (
            <div className="file-row">
              <DocIcon size={18} style={{ color: "var(--text-2)" }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="fr-name">{file.name}</div>
                <div className="fr-meta">{(file.size / 1048576).toFixed(1)} MB · 已就绪</div>
              </div>
              <button type="button" className="btn btn-icon" aria-label="移除文件" onClick={remove} disabled={busy}>
                <CloseIcon />
              </button>
            </div>
          )}
          {error && <ErrorBanner title={error.title} detail={error.detail} />}
          <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: "auto" }}>
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
              取消
            </button>
            <button type="button" className="btn btn-primary" onClick={start} disabled={!file || busy}>
              {busy ? "上传中…" : "开始分析"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
