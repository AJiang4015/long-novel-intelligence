"""P20 evidence dump —— alias→原文上下文 确定性检索（Spec §8；Step 2）。

- **零 LLM**：用与 ingest 相同配置对 corpus 重新 read_epub + chunk_chapters（确定性），
  文本检索 mention 出现位置 → `{alias, chunk_id, chapter_id, snippet(±window)}`；
- 供人工可解释性复核（P18 Do Not Reopen 纪律：顺顺 aliases 逐条原文核对）；
  复核结论由人工回填 annotation（报告层处理，Step 3），本模块**只产证据，不判定**；
- 可选增强（ER_LINEAGE=1 时并入 judge 事件）为后续迭代，本步只做确定性检索
  （Spec §8「可选增强」；D-8：lineage 是旁路 observer，只读）。

用法（runner 调用，不单独作为 CLI）：
    from tools.eval_framework.evidence import collect_alias_contexts
"""

from __future__ import annotations

from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import read_epub


def _occurrences(haystack: str, needle: str) -> list[int]:
    """needle 在 haystack 中的全部出现位置（确定性；空 needle 返回空）。"""
    if not needle:
        return []
    out: list[int] = []
    start = 0
    while True:
        pos = haystack.find(needle, start)
        if pos < 0:
            return out
        out.append(pos)
        start = pos + len(needle)


def _snippet(text: str, pos: int, length: int, window: int) -> str:
    start = max(0, pos - window)
    end = min(len(text), pos + length + window)
    return text[start:end]


def collect_alias_contexts(epub_bytes: bytes, *, chunk_size: int, chunk_overlap: int,
                           persons: list[dict], window: int = 40,
                           max_per_alias: int = 5) -> dict:
    """对每个 canonical（name + aliases）产出原文上下文证据。

    输入 persons = 最终图快照的 persons（name / aliases；与 runner 快照同构）。
    返回：
        {"persons": [{"canonical": str, "aliases": [str, ...],
                      "alias_contexts": [{"alias", "chunk_id", "chapter_id", "snippet"}]}]}
    """
    chapters = read_epub(epub_bytes)
    chunks = chunk_chapters(chapters, chunk_size, chunk_overlap)

    out_persons: list[dict] = []
    for p in persons:
        mentions = [p.get("name", ""), *(p.get("aliases") or [])]
        contexts: list[dict] = []
        for mention in mentions:
            count = 0
            for ch in chunks:
                if count >= max_per_alias:
                    break
                if mention not in ch.text:
                    continue
                for pos in _occurrences(ch.text, mention):
                    if count >= max_per_alias:
                        break
                    contexts.append({
                        "alias": mention,
                        "chunk_id": ch.chunk_id,
                        "chapter_id": ch.chapter_id,
                        "snippet": _snippet(ch.text, pos, len(mention), window),
                    })
                    count += 1
        out_persons.append({
            "canonical": p.get("name", ""),
            "aliases": p.get("aliases") or [],
            "alias_contexts": contexts,
        })
    return {"persons": out_persons}
