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


from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import Chapter


def test_chunk_short_chapter_is_single_chunk():
    chapter = Chapter(chapter_id=1, chapter_title="第一章", text="甲乙丙" * 10)
    chunks = chunk_chapters([chapter], chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == 1
    assert chunks[0].chapter_id == 1
    assert chunks[0].start_offset == 0
    assert chunks[0].end_offset == 30


def test_chunk_long_chapter_splits_with_overlap():
    chapter = Chapter(chapter_id=2, chapter_title="第二章", text="x" * 1000)
    chunks = chunk_chapters([chapter], chunk_size=300, overlap=50)
    assert len(chunks) == 4
    assert [c.start_offset for c in chunks] == [0, 250, 500, 750]
    assert chunks[0].end_offset == 300
    assert all(c.chapter_id == 2 for c in chunks)
    assert [c.chunk_id for c in chunks] == [1, 2, 3, 4]


def test_chunk_offsets_relative_to_chapter_text():
    chapter = Chapter(chapter_id=1, chapter_title="第一章", text="abcdefghij")
    chunks = chunk_chapters([chapter], chunk_size=4, overlap=1)
    assert chunks[0].start_offset == 0 and chunks[0].end_offset == 4
    assert chunks[1].start_offset == 3 and chunks[1].end_offset == 7
    assert chunks[2].start_offset == 6 and chunks[2].end_offset == 10


def test_chunk_ids_global_across_chapters():
    chapters = [
        Chapter(chapter_id=1, chapter_title="第一章", text="a" * 50),
        Chapter(chapter_id=2, chapter_title="第二章", text="b" * 500),
    ]
    chunks = chunk_chapters(chapters, chunk_size=300, overlap=0)
    assert [c.chunk_id for c in chunks] == [1, 2, 3]
    assert [c.chapter_id for c in chunks] == [1, 2, 2]
