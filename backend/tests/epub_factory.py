import io

from ebooklib import epub


def build_epub(chapters: list[str]) -> bytes:
    """构造一个章节为纯文本的测试 EPUB，直接返回文件字节（不落盘，避免临时目录依赖）。"""
    book = epub.EpubBook()
    book.set_identifier("test-001")
    book.set_title("测试小说")
    book.set_language("zh")
    spine = []
    for i, text in enumerate(chapters, start=1):
        c = epub.EpubHtml(title=f"第{i}章", file_name=f"chap_{i}.xhtml", lang="zh")
        # 空章节不生成标题/段落内容，确保剥离 HTML 后 text 为空（用于测试空章节跳过）
        c.content = f"<h1>第{i}章</h1><p>{text}</p>" if text else "<p></p>"
        book.add_item(c)
        spine.append(c)
    book.toc = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()
