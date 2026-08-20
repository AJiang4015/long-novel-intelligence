import { useRef, useState } from "react";
import { uploadNovel } from "../api";

interface Props {
  onUploaded: (novelId: string, jobId: string) => void;
}

export default function Upload({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".epub")) {
      setError("仅支持 .epub 文件");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const { novel_id, job_id } = await uploadNovel(file);
      onUploaded(novel_id, job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div
        style={{ border: "2px dashed #999", borderRadius: 8, padding: 40, textAlign: "center", cursor: "pointer" }}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleFile(e.dataTransfer.files?.[0]);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".epub"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
        {busy ? "上传中…" : "拖拽或点击上传 .epub 小说"}
      </div>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
