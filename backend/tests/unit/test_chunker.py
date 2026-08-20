from app.pipeline.epub_reader import read_epub
from tests.epub_factory import build_epub


def test_read_epub_extracts_chapters_in_spine_order():
    epub_bytes = build_epub(["第一段内容。", "第二段内容。"])
    chapters = read_epub(epub_bytes)
    assert [c.chapter_title for c in chapters] == ["第1章", "第2章"]
    assert chapters[0].chapter_id == 1
    assert chapters[1].chapter_id == 2
    assert "第一段内容" in chapters[0].text
    assert "第二段内容" in chapters[1].text
    assert "<h1>" not in chapters[0].text  # HTML 标签已剥离


def test_read_epub_skips_empty_chapter():
    epub_bytes = build_epub(["", "有内容的章节。"])
    chapters = read_epub(epub_bytes)
    assert len(chapters) == 1
    assert chapters[0].chapter_id == 1
    assert "有内容的章节" in chapters[0].text
