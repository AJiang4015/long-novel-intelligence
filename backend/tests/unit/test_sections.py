"""V0.2.5-a section 分类器测试（deterministic，不调 LLM）。"""
from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import Chapter
from app.pipeline.sections import SectionType, classify_chapter


def cls(title="第1章", text="正文内容", index=0, total=1):
    return classify_chapter(title, text, index, total)


# ---- T-a11：内容标记分类 ----

def test_metadata_copyright_first_line():
    assert cls(text="版权信息\n边城\n作者：沈从文") == SectionType.METADATA


def test_epigraph_ticji_first_line():
    assert cls(text="题记\n对于农人与兵士…") == SectionType.EPIGRAPH


def test_epigraph_xin_ticji_first_line():
    assert cls(text="新题记\n民十随部队入川…") == SectionType.EPIGRAPH


def test_trailer_ad_first_line():
    assert cls(text="关注公众号：zuixiaoyao\n微信搜索…") == SectionType.TRAILER


# ---- T-a11：正文序号 → BODY ----

def test_body_first_line_bare_numeral():
    assert cls(text="一\n由四川过湖南去…") == SectionType.BODY


def test_body_first_line_numeral_with_content():
    assert cls(text="二 茶峒地方凭水依山筑城…") == SectionType.BODY
    assert cls(text="二一 大清早…") == SectionType.BODY


def test_body_first_line_di_n():
    assert cls(text="第1章 由四川过湖南去…") == SectionType.BODY
    assert cls(text="第一章 由四川过湖南去…") == SectionType.BODY


# ---- 标题关键词 ----

def test_title_keywords_override_content():
    assert cls(title="题记", text="随便") == SectionType.EPIGRAPH
    assert cls(title="版权页", text="随便") == SectionType.METADATA
    assert cls(title="后记", text="随便") == SectionType.TRAILER


# ---- T-a12：保守默认 BODY ----

def test_unknown_first_line_defaults_to_body():
    assert cls(text="从前有座山，山里有座庙…") == SectionType.BODY


def test_empty_text_defaults_to_body():
    assert cls(text="") == SectionType.BODY


# ---- 位置弱信号（仅兜底）----

def test_position_fallback_first_short_copyright():
    assert cls(text="版权\n作者：佚名", index=0, total=10) == SectionType.METADATA


def test_position_fallback_last_short_ad():
    assert cls(text="关注我们\nhttps://mp.weixin.qq.com/xxx", index=9, total=10) == SectionType.TRAILER


def test_position_fallback_does_not_override_body_length():
    # 首章但内容长（非版权特征）→ 不按位置兜底
    assert cls(text="正文" * 200, index=0, total=10) == SectionType.BODY


# ---- T-a13：chunk 继承 section_type，不混 section ----

def test_chunk_inherits_section_type():
    chapters = [
        Chapter(1, "一", "正文" * 100, SectionType.BODY),
        Chapter(2, "题记", "题记" * 100, SectionType.EPIGRAPH),
    ]
    chunks = chunk_chapters(chapters, chunk_size=50, overlap=10)
    assert chunks
    assert all(c.section_type == SectionType.BODY for c in chunks if c.chapter_id == 1)
    assert all(c.section_type == SectionType.EPIGRAPH for c in chunks if c.chapter_id == 2)
    assert all(c.chapter_id in (1, 2) for c in chunks)
