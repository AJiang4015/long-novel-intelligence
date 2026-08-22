"""V0.2.4 mention hygiene 测试（mock extract/judge，不调真实 LLM）。"""
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import (AliasJudgeResult, Character, ExtractionResult,
                             MentionCategory)


def make_chunk(chunk_id, chapter_id=1, text="文本"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(names, categories=None):
    """categories: dict[name, MentionCategory|None]；缺省 None（legacy）。"""
    chars = []
    for n in names:
        item = {"name": n}
        if categories and categories.get(n) is not None:
            item["category"] = categories[n].value
        chars.append(item)
    return ExtractionResult.model_validate({"characters": chars, "relationships": []})


def judge_null(text, pending):
    return AliasJudgeResult.model_validate(
        {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})


def test_character_category_optional_legacy():
    """旧版 ExtractionResult 无 category → 解析成功，category=None。"""
    r = ExtractionResult.model_validate({"characters": [{"name": "天保"}], "relationships": []})
    assert r.characters[0].category is None


def test_character_category_enum():
    """category 用 Enum 校验；非法值拒绝。"""
    r = ExtractionResult.model_validate(
        {"characters": [{"name": "两个儿子", "category": "collective"}], "relationships": []})
    assert r.characters[0].category == MentionCategory.COLLECTIVE
    with pytest.raises(Exception):
        ExtractionResult.model_validate(
            {"characters": [{"name": "X", "category": "banana"}], "relationships": []})


# ---------- Task 2: deterministic hard rules ----------
from app.pipeline.hygiene import classify_mention, is_hard_filtered


@pytest.mark.parametrize("name", ["两个儿子", "兄弟二人", "父子三人", "两弟兄", "三个儿子"])
def test_hard_filter_collective(name):
    """COLLECTIVE 可 hard filter：两个儿子/兄弟二人/父子三人/两弟兄。"""
    assert is_hard_filtered(name)
    assert classify_mention(name) == MentionCategory.COLLECTIVE


@pytest.mark.parametrize("name", ["", "12345", "!!!", "x" * 60])
def test_hard_filter_invalid(name):
    assert is_hard_filtered(name)
    assert classify_mention(name) == MentionCategory.INVALID


@pytest.mark.parametrize("name", ["弟弟", "妇人", "年青人", "哥哥", "死去的人", "老头子"])
def test_generic_not_hard_filtered(name):
    """GENERIC 不得被 hard rules 过滤——只能由 LLM category 分类，resolver 决策。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None   # hard rules 不返回 GENERIC


@pytest.mark.parametrize("name", ["岳云二老", "天保大老", "天保大人", "傩送二老"])
def test_composite_not_hard_filtered(name):
    """COMPOSITE 不直接过滤。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None


@pytest.mark.parametrize("name", ["翠翠的祖父", "顺顺大儿子"])
def test_descriptive_not_hard_filtered(name):
    """DESCRIPTIVE 不直接过滤。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None


@pytest.mark.parametrize("name", ["天保", "傩送", "翠翠", "祖父", "顺顺", "王团总"])
def test_person_not_hard_filtered(name):
    """正常专名不误伤。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None
