from dataclasses import dataclass

from app.pipeline.epub_reader import Chapter


@dataclass
class Chunk:
    chunk_id: int
    chapter_id: int
    chapter_title: str
    text: str
    start_offset: int
    end_offset: int


def chunk_chapters(chapters: list[Chapter], chunk_size: int, overlap: int) -> list[Chunk]:
    """章节 → 文本块。

    - 整章 ≤ chunk_size 为一块；
    - 超长章按 chunk_size 切，相邻块重叠 overlap 字符（同章内）；
    - offset 为相对该章节纯文本的字符偏移；
    - chunk_id 全局递增。
    """
    chunks: list[Chunk] = []
    chunk_id = 1
    for chapter in chapters:
        text = chapter.text
        if not text:
            continue
        if len(text) <= chunk_size:
            chunks.append(Chunk(chunk_id, chapter.chapter_id, chapter.chapter_title, text, 0, len(text)))
            chunk_id += 1
            continue
        step = max(1, chunk_size - overlap)
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(Chunk(chunk_id, chapter.chapter_id, chapter.chapter_title, text[start:end], start, end))
            chunk_id += 1
            if end == len(text):
                break
            start += step
    return chunks
