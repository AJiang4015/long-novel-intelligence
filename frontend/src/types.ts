/** 类型定义：前后端共享的数据结构（任务/小说/人物/图谱/证据等） */
export type JobStatus = "pending" | "running" | "completed" | "completed_with_errors" | "failed";

/** 分析任务进度：已完成块数 / 总块数 */
export interface JobProgress {
  done_chunks: number;
  total_chunks: number;
}

/** 失败的文本块（含其归属章节与错误信息） */

export interface FailedBlock {
  chunk_id: number;
  chapter_id: number;
  error: string;
}

/** 分析任务响应：含状态、进度、失败块与统计信息 */
export interface JobResponse {
  job_id: string;
  novel_id: string;
  status: JobStatus;
  progress: JobProgress;
  failed_blocks: FailedBlock[];
  stats: Record<string, number>;
  error?: string | null;
}

/** 小说信息：标题、章节列表与整体统计 */
export interface NovelResponse {
  id: string;
  title: string;
  chapters: { id: number; title: string }[];
  stats: Record<string, number>;
}

/** 人物候选：搜索/中心人物通用结构（含提及次数） */
export interface CharacterCandidate {
  id: string;
  name: string;
  mention_count: number;
}

/** 原文证据片段（归属章节与引用文本） */
export interface Evidence {
  chunk_id: number;
  chapter_id: number;
  chapter_title: string;
  text: string;
}

/** 图谱节点：人物，is_center 标识中心人物 */
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

/** 图谱响应：节点与边集合 */
export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
