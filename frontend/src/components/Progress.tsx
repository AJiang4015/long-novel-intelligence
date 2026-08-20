import { useEffect, useState } from "react";
import { getJob } from "../api";
import type { JobResponse } from "../types";

const TERMINAL: string[] = ["completed", "completed_with_errors", "failed"];

interface Props {
  jobId: string;
  onDone: (job: JobResponse) => void;
}

export default function Progress({ jobId, onDone }: Props) {
  const [job, setJob] = useState<JobResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const j = await getJob(jobId);
        if (cancelled) return;
        setJob(j);
        if (TERMINAL.includes(j.status)) {
          clearInterval(timer);
          onDone(j);
        }
      } catch {
        /* 轮询瞬时错误忽略，下一轮重试 */
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, onDone]);

  if (!job) return <p>正在分析小说…</p>;

  const { done_chunks, total_chunks } = job.progress;
  const pct = total_chunks > 0 ? Math.round((done_chunks / total_chunks) * 100) : 0;

  return (
    <div>
      <p>
        正在分析小说：{done_chunks} / {total_chunks} chunks · {pct}%
      </p>
      <div style={{ width: "100%", background: "#eee", borderRadius: 4, height: 12 }}>
        <div style={{ width: `${pct}%`, background: "#4caf50", height: 12, borderRadius: 4 }} />
      </div>
      {job.status === "completed_with_errors" && (
        <p style={{ color: "orange" }}>{job.failed_blocks.length} 个文本块抽取失败，已跳过</p>
      )}
      {job.status === "failed" && <p style={{ color: "red" }}>分析失败：{job.error ?? "未知错误"}</p>}
    </div>
  );
}
