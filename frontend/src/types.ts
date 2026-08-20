export type JobStatus = "pending" | "running" | "completed" | "completed_with_errors" | "failed";

export interface JobProgress {
  done_chunks: number;
  total_chunks: number;
}

export interface FailedBlock {
  chunk_id: number;
  chapter_id: number;
  error: string;
}

export interface JobResponse {
  job_id: string;
  novel_id: string;
  status: JobStatus;
  progress: JobProgress;
  failed_blocks: FailedBlock[];
  stats: Record<string, number>;
  error?: string | null;
}

export interface NovelResponse {
  id: string;
  title: string;
  chapters: { id: number; title: string }[];
  stats: Record<string, number>;
}

export interface CharacterCandidate {
  id: string;
  name: string;
  mention_count: number;
}

export interface Evidence {
  chunk_id: number;
  chapter_id: number;
  chapter_title: string;
  text: string;
}

export interface GraphNode {
  id: string;
  name: string;
  mention_count: number;
  is_center: boolean;
}

export interface GraphEdge {
  source_id: string;
  target_id: string;
  type: string;
  weight: number;
  confidence: number;
  evidence: Evidence[];
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---- 薄转换层：force-graph 内部状态与后端 DTO 隔离 ----

export interface ForceNode {
  id: string;
  name: string;
  mention_count: number;
  isCenter: boolean;
}

export interface ForceLink {
  source: string;
  target: string;
  type: string;
  weight: number;
  confidence: number;
  evidence: Evidence[];
}

export function toForceGraph(g: GraphResponse): { nodes: ForceNode[]; links: ForceLink[] } {
  const nodes: ForceNode[] = g.nodes.map((n) => ({
    id: n.id,
    name: n.name,
    mention_count: n.mention_count,
    isCenter: n.is_center,
  }));
  const links: ForceLink[] = g.edges.map((e) => ({
    source: e.source_id,
    target: e.target_id,
    type: e.type,
    weight: e.weight,
    confidence: e.confidence,
    evidence: e.evidence,
  }));
  return { nodes, links };
}
