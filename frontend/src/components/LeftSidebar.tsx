/**
 * 左侧栏：novel-card · progress-card（处理中）· stats-grid · 人物搜索 · center-chip · left-foot。
 * 结构与类名逐字取自 design/novel-graph-workbench.html 的 .left（唯一事实来源）。
 * 数字一律 en-US 千分位逗号（1,000，禁止空格）。
 */
import type { CharacterCandidate, GraphResponse, JobResponse, JobStatus, NovelResponse } from "../types";
import CharacterSearch from "./CharacterSearch";

interface LeftSidebarProps {
  novel: NovelResponse | null;
  job: JobResponse | null;
  phase: "empty" | "processing" | "graph";
  center: CharacterCandidate | null;
  graph: GraphResponse | null; // 当前中心子图（center-chip 的 N 人物 · M 关系）
  onSelectCharacter: (c: CharacterCandidate) => void;
}

const fmt = (n: number) => n.toLocaleString("en-US");
/** 缺省显示 — */
const v = (n: number | undefined) => (n == null ? "—" : fmt(n));

const STATUS_TEXT: Record<JobStatus, string> = {
  pending: "等待中",
  running: "分析中",
  completed: "已完成",
  completed_with_errors: "部分完成",
  failed: "分析失败",
};

export default function LeftSidebar({
  novel,
  job,
  phase,
  center,
  graph,
  onSelectCharacter,
}: LeftSidebarProps) {
  const statusText = job ? STATUS_TEXT[job.status] : phase === "processing" ? "分析中" : "未分析";

  const pct =
    job && job.progress.total_chunks > 0
      ? Math.round((job.progress.done_chunks / job.progress.total_chunks) * 100)
      : 0;

  const subgraphText = graph
    ? graph.nodes.length <= 1
      ? "孤立"
      : `1-hop 子图 · ${fmt(graph.nodes.length)} 人物 · ${fmt(graph.edges.length)} 关系`
    : null;

  return (
    <aside className="left">
      {/* 小说卡 */}
      <section className="panel novel-card">
        <div className="nc-head">
          <span className="nc-name">{novel ? novel.title : "未选择小说"}</span>
          {novel && <span className="badge badge-accent">已分析</span>}
        </div>
        <div className="nc-meta">
          <span>
            章回 <span className="num">{novel ? fmt(novel.chapters.length) : "—"}</span> · 文本块{" "}
            <span className="num">{job ? fmt(job.progress.total_chunks) : "—"}</span>
          </span>
          <span>
            分析状态 <span>{statusText}</span>
          </span>
        </div>
      </section>

      {/* 处理中：进度卡 */}
      {phase === "processing" && job && (
        <section className="progress-card">
          <div className="pc-head">
            <span>分析进度</span>
            <span className="badge badge-warning badge-running">
              <span className="dot"></span>分析中
            </span>
          </div>
          <div className="progress progress-lg">
            <div className="progress-fill is-running" style={{ width: `${pct}%` }}></div>
          </div>
          <div className="pc-nums">
            {fmt(job.progress.done_chunks)} / {fmt(job.progress.total_chunks)} 块 · {pct}%
          </div>
        </section>
      )}

      {/* 非处理中：2×2 统计 */}
      {phase !== "processing" && (
        <section>
          <div className="left-sec-title">
            <span className="section-title">小说统计</span>
            <span className="detail-note">来自分析结果</span>
          </div>
          <div className="stats-grid">
            <div className="stat-cell">
              <span className="stat-value num">{v(job?.stats?.persons)}</span>
              <span className="stat-label">人物</span>
            </div>
            <div className="stat-cell">
              <span className="stat-value num">{v(job?.stats?.relationships)}</span>
              <span className="stat-label">关系</span>
            </div>
            <div className="stat-cell">
              <span className="stat-value num">{v(novel?.chapters.length)}</span>
              <span className="stat-label">章节</span>
            </div>
            <div className="stat-cell">
              <span className="stat-value num">{v(job?.progress.total_chunks)}</span>
              <span className="stat-label">文本块</span>
            </div>
          </div>
        </section>
      )}

      {/* 人物搜索 */}
      <section>
        <div className="left-sec-title">
          <span className="section-title">人物搜索</span>
        </div>
        {novel && <CharacterSearch novelId={novel.id} onSelect={onSelectCharacter} />}
      </section>

      {/* 当前中心人物 */}
      {phase === "graph" && center && (
        <section className="center-chip">
          <div className="left-sec-title" style={{ marginBottom: 0 }}>
            <span className="section-title">当前中心人物</span>
          </div>
          <div className="cc-name">
            <span className="cc-name-text">{center.name}</span>
            <span className="badge badge-accent">中心</span>
          </div>
          <div className="cc-sub">
            <span className="num">提及 {fmt(center.mention_count)} 块</span>
          </div>
          {subgraphText && <div className="cc-sub">{subgraphText}</div>}
        </section>
      )}

      {/* 底部说明 */}
      <div className="left-foot">
        <span>界面演示使用《红楼梦》示例数据，仅用于展示分析结果样式。</span>
        <a className="foot-link" href="/design-system.html">
          查看设计系统规范 ↗
        </a>
      </div>
    </aside>
  );
}
