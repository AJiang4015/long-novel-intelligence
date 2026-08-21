/** API 层：封装后端接口调用（上传/任务/小说/人物搜索/图谱） */
import type { CharacterCandidate, GraphResponse, JobResponse, NovelListItem, NovelResponse } from "./types";

/** 统一响应处理：非 2xx 抛错（优先取后端 detail 字段），成功解析 JSON */
async function handle<T>(resp: Response | Promise<Response>): Promise<T> {
  const r = await resp;
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    throw new Error((body && body.detail) || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

/** 上传小说文件，返回 new novel_id 与 job_id */
export async function uploadNovel(file: File): Promise<{ novel_id: string; job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return handle(fetch("/api/novels", { method: "POST", body: form }));
}

/** 查询分析任务状态/进度 */
export function getJob(jobId: string): Promise<JobResponse> {
  return handle(fetch(`/api/jobs/${jobId}`));
}

/** 查询小说基本信息（标题/章节/统计） */
export function getNovel(novelId: string): Promise<NovelResponse> {
  return handle(fetch(`/api/novels/${novelId}`));
}

/** 列出全部已有小说（启动恢复探测用） */
export function listNovels(): Promise<NovelListItem[]> {
  return handle(fetch("/api/novels"));
}

/** 按关键词搜索小说内的人物 */
export function searchCharacters(novelId: string, q: string): Promise<CharacterCandidate[]> {
  return handle(fetch(`/api/novels/${novelId}/characters?q=${encodeURIComponent(q)}`));
}

/** 获取某人物为中心的 1-hop 关系子图 */
export function getGraph(characterId: string): Promise<GraphResponse> {
  return handle(fetch(`/api/characters/${characterId}/graph`));
}
