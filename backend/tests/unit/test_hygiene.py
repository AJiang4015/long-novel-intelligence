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
