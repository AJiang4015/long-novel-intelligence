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


# ═══════════ 同 chunk 共现召回（V0.2 第二步第 1 项）═══════════

def test_cooccurrence_recalls_zero_overlap_alias_in_same_chunk():
    """零共享字但同 chunk 共现（傩送 先确认，二老 后出现）→ 共现召回成功并经 judge 合并。"""
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="傩送撑船"), extraction(["傩送"]))  # 确立 canonical
    out, _ = r.resolve(make_chunk(2, text="二老和傩送同在一处"), extraction(["傩送", "二老"]))
    assert [c.name for c in out.characters] == ["傩送", "傩送"]
    assert r.canonical_aliases["傩送"] == ["二老"]
    assert j.calls == 1


def test_cooccurrence_candidate_priority_over_char_overlap():
    """同 chunk 共现候选优先级高于普通字符重合候选（共现 傩送 排在字符重合 大老 之前）。"""
    seen: dict = {}

    def recorder(text, pending):
        seen["cands"] = [[c.canonical for c in p.candidates] for p in pending]
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})

    r = EntityResolver(judge=recorder)
    r.resolve(make_chunk(1), extraction(["傩送", "大老"]))
    r.resolve(make_chunk(2, text="二老和傩送同在一处"), extraction(["傩送", "二老"]))
    # chunk2：傩送 已知先确认 → 二老 候选 = [傩送(共现优先), 大老(字符重合 老)]
    assert seen["cands"] == [["傩送", "大老"]]


def test_no_cooccurrence_across_chunks_requires_llm_judgment():
    """不同 chunk 且无字符重合 → 不自动合并；仍走候选 + LLM 判定（判 null 则独立 canonical）。"""
    j = _Judge({"二老": None})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["二老"]))
    assert j.calls == 1  # 走了一次 LLM 判定（零重叠候选仍在 top-k 内）
    assert out.characters[0].name == "二老"  # 判 null → 独立 canonical，不自动合并


def test_cooccurrence_new_canonical_also_feeds_later_names():
    """同 chunk 内新确立的 canonical 也参与后续共现召回（首现规则不受影响）。"""
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    # chunk1：空 index，傩送 无候选 → 新 canonical；二老 与它同 chunk 共现 → 召回成功
    out, _ = r.resolve(make_chunk(1, text="二老和傩送同在一处"), extraction(["傩送", "二老"]))
    assert [c.name for c in out.characters] == ["傩送", "傩送"]
    assert r.canonical_aliases["傩送"] == ["二老"]


def test_cooccurrence_unknown_first_still_recalls_known():
    """顺序敏感性修复：[二老, 傩送] 未知在前，预扫描后 二老 仍能召回 傩送 并经 judge 合并。"""
    # 饱和 top-5：7 个 canonical 使「老」字重叠占满字符候选（傩送 零重叠会被挤出，全靠共现）
    seed = ["傩送", "大老", "老人", "老船夫", "老马兵", "老道士", "老婆子"]
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, "A"), extraction(seed))
    out, _ = r.resolve(make_chunk(2, "B"), extraction(["二老", "傩送"]))  # 未知在前
    assert [c.name for c in out.characters] == ["傩送", "傩送"]
    assert "二老" in r.canonical_aliases["傩送"]


def test_cooccurrence_candidates_identical_both_orders():
    """两种顺序（二老先/后）下 二老 的候选集合一致，且都含 傩送。"""
    def build(chunk2_names):
        seen: dict = {}

        def recorder(text, pending):
            seen["cands"] = [[c.canonical for c in p.candidates] for p in pending]
            return AliasJudgeResult.model_validate(
                {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})

        r = EntityResolver(judge=recorder)
        r.resolve(make_chunk(1, "A"), extraction(["傩送", "大老", "老人", "老船夫", "老马兵", "老道士", "老婆子"]))
        seen.clear()
        r.resolve(make_chunk(2, "B"), extraction(chunk2_names))
        return seen.get("cands")

    cands_unknown_first = build(["二老", "傩送"])
    cands_known_first = build(["傩送", "二老"])
    assert cands_unknown_first is not None and cands_known_first is not None
    assert cands_unknown_first[0] == cands_known_first[0]
    assert "傩送" in cands_unknown_first[0]
