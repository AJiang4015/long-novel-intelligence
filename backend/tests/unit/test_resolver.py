import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import AliasJudgeResult, ExtractionResult


def make_chunk(chunk_id, chapter_id=1, text="文本"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(names, rels=None):
    return ExtractionResult.model_validate({
        "characters": [{"name": n} for n in names],
        "relationships": rels or [],
    })


def judge_null(text, pending):
    return AliasJudgeResult.model_validate(
        {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})


class _Judge:
    def __init__(self, mapping):
        self.mapping = mapping  # mention -> canonical | None
        self.calls = 0

    def __call__(self, text, pending):
        self.calls += 1
        return AliasJudgeResult.model_validate({
            "resolutions": [
                {"mention": p.mention, "resolves_to": self.mapping.get(p.mention)}
                for p in pending
            ],
        })


def test_new_name_no_candidate_is_new_canonical_no_llm():
    j = _Judge({})
    r = EntityResolver(judge=j)
    out, failed = r.resolve(make_chunk(1), extraction(["傩送"]))
    assert out.characters[0].name == "傩送"
    assert j.calls == 0
    assert r.canonical_aliases == {"傩送": []}


def test_one_judge_call_per_chunk():
    """每 chunk 至多一次 judge：一个 chunk 内多个未知 mention 批量判定（known 整本持续，已确认的别名不再进 pending）。"""
    j = _Judge({"傩二": "傩送", "二送": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="傩送是哥哥"), extraction(["傩送"]))
    out, failed = r.resolve(make_chunk(2, text="傩二和二送都来了"), extraction(["傩二", "二送"]))
    assert j.calls == 1  # 两个未知 mention 一次批量判定
    assert [c.name for c in out.characters] == ["傩送", "傩送"]


def test_judged_alias_points_to_existing_canonical():
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["二老"]))
    assert out.characters[0].name == "傩送"
    assert r.canonical_aliases["傩送"] == ["二老"]


def test_judge_null_creates_new_canonical_no_second_round():
    """判 null → 新 canonical；再次出现缓存命中，不做第二轮。"""
    j = _Judge({"李四": None})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["李三"]))
    out, _ = r.resolve(make_chunk(2), extraction(["李四"]))
    assert out.characters[0].name == "李四"
    assert j.calls == 1
    out2, _ = r.resolve(make_chunk(3), extraction(["李四"]))
    assert out2.characters[0].name == "李四"
    assert j.calls == 1  # 缓存命中，不二轮


def test_judge_validation_failure_isolates_and_records():
    def failing_judge(text, pending):
        raise ValueError("judge boom")

    r = EntityResolver(judge=failing_judge)
    r.resolve(make_chunk(1), extraction(["大老"]))  # seed canonical
    out, failed = r.resolve(make_chunk(5, chapter_id=2), extraction(["二老"]))  # 召回大老 → 判定失败
    assert out.characters[0].name == "二老"  # 独立 canonical
    assert failed is True
    assert r.canonical_aliases == {"大老": [], "二老": []}


def test_aliases_deduped_ordered_exclude_canonical():
    j = _Judge({"二老": "傩送", "二老爷": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    r.resolve(make_chunk(2), extraction(["二老"]))
    r.resolve(make_chunk(3), extraction(["二老爷"]))
    r.resolve(make_chunk(4), extraction(["二老"]))  # 缓存命中，不调 LLM
    assert r.canonical_aliases["傩送"] == ["二老", "二老爷"]
    assert "傩送" not in r.canonical_aliases["傩送"]
    assert j.calls == 2


def test_first_occurrence_determines_canonical():
    # Chunk1 二老 → canonical=二老；Chunk2 傩送 → alias
    j = _Judge({"傩送": "二老"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["二老"]))
    out, _ = r.resolve(make_chunk(2), extraction(["傩送"]))
    assert out.characters[0].name == "二老"
    assert r.canonical_aliases["二老"] == ["傩送"]

    # 反过来：Chunk1 傩送 → canonical=傩送；Chunk2 二老 → alias
    j2 = _Judge({"二老": "傩送"})
    r2 = EntityResolver(judge=j2)
    r2.resolve(make_chunk(1), extraction(["傩送"]))
    out2, _ = r2.resolve(make_chunk(2), extraction(["二老"]))
    assert out2.characters[0].name == "傩送"
    assert r2.canonical_aliases["傩送"] == ["二老"]


def test_relationship_endpoints_resolved():
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送", "翠翠"], [
        {"source": "傩送", "target": "翠翠", "type": "love", "confidence": 0.9}]))
    out, _ = r.resolve(make_chunk(2), extraction(["翠翠"], [
        {"source": "二老", "target": "翠翠", "type": "love", "confidence": 0.8}]))
    rel = out.relationships[0]
    assert rel.source == "傩送"
    assert rel.target == "翠翠"
