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
    """GENERIC 不得被 hard rules 直接过滤——只能由 LLM category 或 hygiene 词表分类，resolver 决策。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) in (None, MentionCategory.GENERIC)   # RC3：弟弟/哥哥 由词表归 GENERIC


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


# ---------- Task 3: resolver category 决策 ----------

def test_collective_never_registered():
    """COLLECTIVE 提取输出 → 不注册 canonical，不进任何状态。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert "两个儿子" not in r.known
    assert "两个儿子" not in r._index
    assert "两个儿子" not in r.canonical_aliases


def test_collective_as_relation_endpoint_drops_relation():
    """COLLECTIVE 作 relation endpoint → 不注册 Person，不崩。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["顺顺"]))
    result = ExtractionResult.model_validate({
        "characters": [{"name": "顺顺", "category": "person"},
                       {"name": "两个儿子", "category": "collective"}],
        "relationships": [{"source": "顺顺", "target": "两个儿子", "type": "family", "confidence": 0.9}],
    })
    out, _ = r.resolve(make_chunk(2), result)
    assert "顺顺" in r.known
    assert "两个儿子" not in r.known


def test_generic_with_candidate_goes_to_judge():
    """GENERIC 有候选 → 进入 alias judge；judge 明确通过 → alias。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "年青人" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))   # 建立 canonical
    out, _ = r.resolve(make_chunk(2), extraction(["年青人"], {"年青人": MentionCategory.GENERIC}))
    assert "年青人" in r.known and r.known["年青人"] == "傩送"   # judge 吸收为 alias
    assert "年青人" in r.canonical_aliases["傩送"]
    assert seen["pending"][0][0] == "年青人"
    assert seen["pending"][0][1] == ["傩送"]


def test_generic_no_candidate_dropped():
    """GENERIC 无候选 → 丢弃，不注册 canonical。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["年青人"], {"年青人": MentionCategory.GENERIC}))
    assert "年青人" not in r.known
    assert "年青人" not in r._index
    assert "年青人" not in r.canonical_aliases


def test_generic_does_not_absorb_polluted_collective_canonical():
    """GENERIC 的候选不得含历史污染 COLLECTIVE canonical（_recall 排除硬过滤 canonical）。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})
    r = EntityResolver(judge=j)
    # 模拟历史污染：直接注入 _index（旧数据场景），_recall 应排除它
    r._index["两个儿子"] = {"两个儿子"}
    r.known["两个儿子"] = "两个儿子"
    r.resolve(make_chunk(1), extraction(["傩送"]))   # 建立有效 canonical
    out, _ = r.resolve(make_chunk(2), extraction(["年青人"], {"年青人": MentionCategory.GENERIC}))
    cands = seen["pending"][0][1] if seen.get("pending") else []
    assert "两个儿子" not in cands
    assert "傩送" in cands   # 有效 canonical 正常进入候选


def test_descriptive_with_candidate_goes_to_judge():
    """DESCRIPTIVE 有候选 → 正常 alias judge（翠翠的祖父 → 祖父）。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "祖父" if p.mention == "翠翠的祖父" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["祖父", "翠翠"]))
    out, _ = r.resolve(make_chunk(2), extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert r.known.get("翠翠的祖父") == "祖父"
    assert "翠翠的祖父" in r.canonical_aliases["祖父"]


def test_descriptive_no_candidate_allowed_canonical():
    """DESCRIPTIVE 无候选 → 允许注册 canonical（不静默丢人物）。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert r.known.get("翠翠的祖父") == "翠翠的祖父"


def test_composite_with_candidate_goes_to_judge():
    """COMPOSITE 有候选 → 正常 alias judge（岳云二老 → 傩送）。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "岳云二老" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["岳云二老"], {"岳云二老": MentionCategory.COMPOSITE}))
    assert r.known.get("岳云二老") == "傩送"


def test_category_none_legacy_person_fallback():
    """category=None 且 hard rules 未命中 → legacy PERSON fallback（正常注册）。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["天保"]))   # 无 category
    assert r.known.get("天保") == "天保"   # 正常注册为 canonical


def test_filtered_mention_not_in_merge_evidence():
    """被过滤 mention 不得进入 merge_evidence。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert all("两个儿子" not in ev["mention"] and "两个儿子" not in ev["pair"]
               for ev in r.merge_evidence)


# ---------- V0.2.4-a RC2：硬过滤 mention 输出层彻底剔除 ----------

def extraction_with_rels(names, rels, categories=None):
    """带关系端点的 extraction：rels=[(source, target, type, confidence)]。"""
    chars = []
    for n in names:
        item = {"name": n}
        if categories and categories.get(n) is not None:
            item["category"] = categories[n].value
        chars.append(item)
    return ExtractionResult.model_validate({
        "characters": chars,
        "relationships": [
            {"source": s, "target": t, "type": typ, "confidence": conf}
            for (s, t, typ, conf) in rels
        ],
    })


def test_rc2_collective_not_in_resolved_characters():
    """RC2：两个儿子 被硬过滤 → 不进入 resolved.characters。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1),
                       extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert "两个儿子" not in [c.name for c in out.characters]


def test_rc2_collective_not_in_merged_persons():
    """RC2：完整链 resolve → merge_extractions → 两个儿子 不进 merged.persons。"""
    from app.pipeline.merger import merge_extractions, apply_aliases
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1),
                       extraction(["两个儿子", "顺顺"],
                                  {"两个儿子": MentionCategory.COLLECTIVE}))
    merged = merge_extractions([(make_chunk(1), out)])
    apply_aliases(merged, r.canonical_aliases)
    assert "两个儿子" not in merged.persons
    assert "顺顺" in merged.persons   # 正常 mention 保留


def test_rc2_relationship_target_filtered_dropped():
    """RC2：关系 target 为硬过滤 mention → 整条关系丢弃。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["顺顺"]))
    out, _ = r.resolve(make_chunk(2), extraction_with_rels(
        ["顺顺", "两个儿子"],
        [("顺顺", "两个儿子", "family", 0.9)],
        {"两个儿子": MentionCategory.COLLECTIVE}))
    rels = [(rel.source, rel.target) for rel in out.relationships]
    assert ("顺顺", "两个儿子") not in rels
    assert out.relationships == []   # 整条关系被丢弃


def test_rc2_relationship_source_filtered_dropped():
    """RC2：关系 source 为硬过滤 mention → 整条关系丢弃。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["顺顺"]))
    out, _ = r.resolve(make_chunk(2), extraction_with_rels(
        ["顺顺", "两个儿子"],
        [("两个儿子", "顺顺", "family", 0.9)],
        {"两个儿子": MentionCategory.COLLECTIVE}))
    assert out.relationships == []


def test_rc2_invalid_not_in_output_or_merged():
    """RC2：INVALID（纯数字）同样剔除，不进 resolved.characters / merged.persons。"""
    from app.pipeline.merger import merge_extractions
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["12345", "顺顺"],
                                                  {"12345": MentionCategory.INVALID}))
    assert "12345" not in [c.name for c in out.characters]
    merged = merge_extractions([(make_chunk(1), out)])
    assert "12345" not in merged.persons
    assert "顺顺" in merged.persons


def test_rc2_collective_not_in_merge_evidence_full_chain():
    """RC2：完整链下 两个儿子 不产生 merge_evidence。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["两个儿子", "天保"],
                                        {"两个儿子": MentionCategory.COLLECTIVE}))
    assert all("两个儿子" not in ev["mention"] and "两个儿子" not in ev["pair"]
               for ev in r.merge_evidence)


def test_rc2_no_state_pollution():
    """RC2：被硬过滤 mention 不污染 known/_index/canonical_aliases。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1),
                       extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert "两个儿子" not in r.known
    assert "两个儿子" not in r._index
    assert "两个儿子" not in r.canonical_aliases


def test_rc2_counting_single_entry_when_char_and_rel():
    """RC2 计数语义锁死：characters + relationships 同时含 两个儿子 → collective_filtered == 1。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["顺顺"]))
    out, _ = r.resolve(make_chunk(2), extraction_with_rels(
        ["两个儿子"],
        [("顺顺", "两个儿子", "family", 0.9)],
        {"两个儿子": MentionCategory.COLLECTIVE}))
    assert r.hygiene_stats["collective_filtered"] == 1   # 不是 2
    assert "两个儿子" not in [c.name for c in out.characters]
    assert out.relationships == []


# ---------- V0.2.4-b RC3：RELATIONAL_GENERIC 词表 ----------

def test_rc3_brother_no_candidate_not_registered():
    """RC3：兄弟 无候选 → GENERIC → 不注册 canonical。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(2), extraction(["兄弟"]))
    assert "兄弟" not in r.known
    assert "兄弟" not in r._index
    assert "兄弟" not in r.canonical_aliases
    assert "兄弟" not in [c.name for c in out.characters]   # RC2 语义：不输出
    assert r.hygiene_stats["generic_filtered"] == 1   # 无候选丢弃计数


def test_rc3_brother_with_candidate_judge_true_becomes_alias():
    """RC3：兄弟 有候选 + judge=true → 成为 alias。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "兄弟" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["兄弟"]))
    assert r.known.get("兄弟") == "傩送"   # judge 吸收为 alias
    assert "兄弟" in r.canonical_aliases["傩送"]
    assert r.hygiene_stats["generic_filtered"] == 0   # 成功 alias 不计 filtered


def test_rc3_brother_judge_null_not_registered():
    """RC3：兄弟 有候选但 judge=null → 不注册、不成 alias。"""
    r = EntityResolver(judge=judge_null)   # judge_null 全 null
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["兄弟"]))
    assert "兄弟" not in r.known
    assert "兄弟" not in r.canonical_aliases
    assert "兄弟" not in r._index


def test_rc3_didi_still_alias_resolution():
    """RC3：弟弟 有候选 + judge=true → 仍允许 alias resolution（→傩送）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "弟弟" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["弟弟"]))
    assert r.known.get("弟弟") == "傩送"
    assert "弟弟" in r.canonical_aliases["傩送"]


def test_rc3_furen_still_alias_resolution():
    """RC3：妇人 有候选 + judge=true → 仍允许 alias resolution（→母亲）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "母亲" if p.mention == "妇人" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["母亲"]))
    out, _ = r.resolve(make_chunk(2), extraction(["妇人"]))
    assert r.known.get("妇人") == "母亲"
    assert "妇人" in r.canonical_aliases["母亲"]


def test_rc3_father_mother_grandfather_not_filtered():
    """RC3：父亲/母亲/祖父 不进词表 → 可注册 canonical（正文真实人物）。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(4), extraction(["祖父"]))
    assert r.known.get("祖父") == "祖父"   # 正常注册
    r2 = EntityResolver(judge=judge_null)
    r2.resolve(make_chunk(4), extraction(["父亲"]))
    assert r2.known.get("父亲") == "父亲"
    r3 = EntityResolver(judge=judge_null)
    r3.resolve(make_chunk(4), extraction(["母亲"]))
    assert r3.known.get("母亲") == "母亲"


def test_rc3_brother_no_state_pollution():
    """RC3：兄弟 无候选 → 不污染 known/_index/canonical_aliases。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(2), extraction(["兄弟"]))
    assert "兄弟" not in r.known
    assert "兄弟" not in r._index
    assert "兄弟" not in r.canonical_aliases


def test_rc3_brother_not_in_merge_evidence():
    """RC3：兄弟 无候选 → 不进入 merge_evidence 作为 established canonical。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(2), extraction(["兄弟"]))
    r.resolve(make_chunk(3), extraction(["天保"]))
    assert all("兄弟" not in ev["mention"] and "兄弟" not in ev["pair"]
               for ev in r.merge_evidence)


def test_rc3_exact_word_match_no_substring():
    """RC3 约束 2：精确词匹配——「顺顺的兄弟」不命中 兄弟 词表（描述性 mention 不误伤）。"""
    from app.pipeline.hygiene import classify_mention
    assert classify_mention("兄弟") == MentionCategory.GENERIC
    assert classify_mention("顺顺的兄弟") is None   # 描述性，不命中精确词表


def test_rc3_generic_overrides_llm_person_category():
    """RC3 precedence：LLM 把 兄弟 标为 PERSON，但 hygiene 词表命中 → 强制 GENERIC，不注册 canonical。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(2),
                       extraction(["兄弟"], {"兄弟": MentionCategory.PERSON}))   # LLM 误标 PERSON
    assert "兄弟" not in r.known          # 强制 GENERIC → 不注册
    assert "兄弟" not in r._index
    assert "兄弟" not in r.canonical_aliases
    assert r.hygiene_stats["generic_filtered"] == 1   # 无候选丢弃计数


def test_rc3_generic_overrides_llm_person_with_candidate_judge():
    """RC3 precedence：LLM 标 PERSON + 词表命中 GENERIC → 有候选仍走 judge（不因 PERSON 直接注册）。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "弟弟" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2),
                       extraction(["弟弟"], {"弟弟": MentionCategory.PERSON}))   # LLM 误标 PERSON
    assert r.known.get("弟弟") == "傩送"   # 仍经 judge → alias（未被 PERSON 直接注册为 canonical）
    assert seen["pending"][0][1] == ["傩送"]


def test_rc3_collective_rc2_regression_unchanged():
    """RC3 回归：两个儿子（COLLECTIVE）RC2 语义不变——仍不进 resolved.characters/merged.persons。"""
    from app.pipeline.merger import merge_extractions
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1),
                       extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert "两个儿子" not in [c.name for c in out.characters]
    merged = merge_extractions([(make_chunk(1), out)])
    assert "两个儿子" not in merged.persons
