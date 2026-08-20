import re
from dataclasses import dataclass
from io import BytesIO

from ebooklib import ITEM_DOCUMENT, epub

_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(nbsp|amp|lt|gt|quot);")


@dataclass
class Chapter:
    chapter_id: int
    chapter_title: str
    text: str


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub("", html)
    text = _ENTITY_RE.sub(lambda m: {
        "nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"',
    }[m.group(1)], text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def read_epub(epub_bytes: bytes) -> list[Chapter]:
    """按 spine 顺序解析 EPUB，返回章节纯文本列表。chapter_id 从 1 递增。"""
    book = epub.read_epub(BytesIO(epub_bytes))
    chapters: list[Chapter] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        text = _strip_html(item.get_content().decode("utf-8", errors="ignore"))
        if not text:
            continue
        title = (getattr(item, "title", "") or "").strip() or f"第{len(chapters) + 1}章"
        chapters.append(Chapter(chapter_id=len(chapters) + 1, chapter_title=title, text=text))
    return chapters
