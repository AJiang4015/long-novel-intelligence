import { useState } from "react";
import CharacterSearch from "./components/CharacterSearch";
import GraphView from "./components/GraphView";
import Progress from "./components/Progress";
import Upload from "./components/Upload";
import type { CharacterCandidate, JobResponse } from "./types";

type Phase = "upload" | "processing" | "graph";

export default function App() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [novelId, setNovelId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [center, setCenter] = useState<CharacterCandidate | null>(null);

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h1>长篇小说知识图谱分析系统</h1>

      {phase === "upload" && (
        <Upload
          onUploaded={(nid, jid) => {
            setNovelId(nid);
            setJobId(jid);
            setJob(null);
            setCenter(null);
            setPhase("processing");
          }}
        />
      )}

      {phase === "processing" && jobId && (
        <Progress
          jobId={jobId}
          onDone={(j) => {
            setJob(j);
            if (j.status === "failed") setPhase("upload");
            else setPhase("graph");
          }}
        />
      )}

      {phase === "graph" && novelId && job && (
        <section>
          <p>
            人物 {job.stats?.persons ?? "?"} · 关系 {job.stats?.relationships ?? "?"}
            {job.status === "completed_with_errors" && `（${job.failed_blocks.length} 块失败已跳过）`}
          </p>
          <CharacterSearch novelId={novelId} onSelect={(c) => setCenter(c)} />
          {center ? (
            <GraphView
              characterId={center.id}
              onCenterChange={(id) => setCenter({ id, name: "" } as CharacterCandidate)}
            />
          ) : (
            <p style={{ color: "#888" }}>搜索并选择一个人物，查看其关系网络。</p>
          )}
          <button onClick={() => setPhase("upload")}>上传新小说</button>
        </section>
      )}
    </main>
  );
}
