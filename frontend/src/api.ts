import type { CharacterCandidate, GraphResponse, JobResponse, NovelResponse } from "./types";

async function handle<T>(resp: Response | Promise<Response>): Promise<T> {
  const r = await resp;
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    throw new Error((body && body.detail) || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export async function uploadNovel(file: File): Promise<{ novel_id: string; job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return handle(fetch("/api/novels", { method: "POST", body: form }));
}

export function getJob(jobId: string): Promise<JobResponse> {
  return handle(fetch(`/api/jobs/${jobId}`));
}

export function getNovel(novelId: string): Promise<NovelResponse> {
  return handle(fetch(`/api/novels/${novelId}`));
}

export function searchCharacters(novelId: string, q: string): Promise<CharacterCandidate[]> {
  return handle(fetch(`/api/novels/${novelId}/characters?q=${encodeURIComponent(q)}`));
}

export function getGraph(characterId: string): Promise<GraphResponse> {
  return handle(fetch(`/api/characters/${characterId}/graph`));
}
