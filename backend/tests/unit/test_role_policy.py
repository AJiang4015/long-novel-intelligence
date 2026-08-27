"""V0.2.6 P16-b role alias 准入策略测试（deterministic，mock judge）。

TDD：先于实现编写；旧行为（judge resolves_to 无条件 alias）下 M1/M2/M4/M5/M6/M7/M8/
M11/M12/M13/M16/M17/M18 应红色失败，M9/M10/M14/M15/M19 保持绿。
"""
from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.pipeline.sections import SectionType
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MentionCategory


def make_chunk(chunk_id, text="文本", section_type=SectionType.BODY):
    return Chunk(chunk_id=chunk_id, chapter_id=chunk_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text), section_type=section_type)


def extraction(names, categories=None):
    chars = []
    for n in names:
        item = {"name": n}
        if categories and categories.get(n) is not None:
            item["category"] = categories[n].value
        chars.append(item)
    return ExtractionResult.model_validate({"characters": chars, "relationships": []})


def judge_resolves(mapping):
    """mock judge：mention -> resolves_to canonical（缺省 null）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": mapping.get(p.mention)} for p in pending]})
    return j


P = MentionCategory.PERSON
D = MentionCategory.DESCRIPTIVE
G = MentionCategory.GENERIC


# ---------- bare：证据门槛 ----------

def test_m1_bare_single_evidence_no_alias():
    """M1：单次合法 父亲→顺顺 → observation，不 alias、输出剔除。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert "父亲" not in r.known
    assert "父亲" not in r.canonical_aliases.get("顺顺", [])
    assert out.characters == []


def test_m2_two_chunks_confirm_alias():
    """M2：两次不同 chunk 独立证据 → confirmed → alias。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert "父亲" not in r.known          # 第一次不 alias
    out, _ = r.resolve(make_chunk(3, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert r.known.get("父亲") == "顺顺"   # 第二次确认
    assert "父亲" in r.canonical_aliases["顺顺"]


def test_m4_multi_candidate_keeps_judge_path():
    """M4：多候选 role → 保持 judge 路径；observation 需二次确认。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "祖父"}))
    r.resolve(make_chunk(1, text="祖父顺顺"), extraction(["祖父", "顺顺"], {"祖父": P, "顺顺": P}))
    out, _ = r.resolve(make_chunk(2, text="祖父顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert "父亲" not in r.known          # observation（1 证据）
    out, _ = r.resolve(make_chunk(3, text="祖父顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert r.known.get("父亲") == "祖父"   # 二次确认


def test_m6_same_chunk_duplicate_not_independent():
    """M6：同一错误上下文重复两次（同 chunk）→ 证据去重 = 1 → 不 alias。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺翠翠"), extraction(["顺顺", "翠翠"], {"顺顺": P, "翠翠": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺"),
                       extraction(["翠翠的父亲", "翠翠的父亲"], {"翠翠的父亲": D}))
    assert "翠翠的父亲" not in r.known
    assert "翠翠的父亲" not in r.canonical_aliases.get("顺顺", [])


def test_m7_qualified_and_bare_mix():
    """M7：限定 + 裸混合，judge 均判 顺顺 → 各自不可确认/observation，互不干扰。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的父亲": "顺顺", "父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺翠翠"), extraction(["顺顺", "翠翠"], {"顺顺": P, "翠翠": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺"),
                       extraction(["翠翠的父亲", "父亲"], {"翠翠的父亲": D, "父亲": D}))
    assert "翠翠的父亲" not in r.known
    assert "父亲" not in r.known


def test_m8_confirmed_alias_regression():
    """M8：confirmed 后不再剔除，直接 alias。"""
    r = EntityResolver(judge=judge_resolves({"爸爸": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    r.resolve(make_chunk(2, text="顺顺爸爸"), extraction(["爸爸"], {"爸爸": D}))
    assert "爸爸" not in r.known          # 1 证据
    r.resolve(make_chunk(3, text="顺顺爸爸"), extraction(["爸爸"], {"爸爸": D}))
    assert r.known.get("爸爸") == "顺顺"   # confirmed
    out, _ = r.resolve(make_chunk(4, text="顺顺爸爸"), extraction(["爸爸"], {"爸爸": D}))
    assert any(c.name == "顺顺" for c in out.characters)   # 直接归并输出


def test_m11_single_evidence_no_conflict_never_confirmed():
    """M11：1 evidence + 无 conflict → 全书末仍保持 observation（gate 不被绕过）。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert "父亲" not in r.known          # 无任何 finalize/末次晋升路径
    assert "父亲" not in r.canonical_aliases


def test_m12_cross_canonical_conflict_blocked():
    """M12：父亲 ch1→顺顺、ch2→祖父 → blocked，全部作废，永不确定。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺祖父"), extraction(["顺顺", "祖父"], {"顺顺": P, "祖父": P}))
    r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    r._judge = judge_resolves({"父亲": "祖父"})   # 第二 chunk 判另一 canonical
    r.resolve(make_chunk(3, text="祖父父亲"), extraction(["父亲"], {"父亲": D}))
    assert "父亲" not in r.known
    assert "父亲" not in r.canonical_aliases.get("顺顺", [])
    assert "父亲" not in r.canonical_aliases.get("祖父", [])


def test_m13_cross_canonical_conflict_variant():
    """M13：两 canonical 各 1 证据 → blocked（不允许分别累计独立确认）。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺祖父"), extraction(["顺顺", "祖父"], {"顺顺": P, "祖父": P}))
    r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    r._judge = judge_resolves({"父亲": "祖父"})
    r.resolve(make_chunk(3, text="祖父父亲"), extraction(["父亲"], {"父亲": D}))
    # 第三次出现仍不 alias（blocked 持续）
    r.resolve(make_chunk(4, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    assert "父亲" not in r.known
    assert r._role_blocked == {"父亲"}


# ---------- qualified ----------

def test_m5_qualified_mismatch_no_alias():
    """M5：翠翠的父亲 → 顺顺（anchor 翠翠 ∉ 候选）→ target-mismatch 不可确认。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺翠翠"), extraction(["顺顺", "翠翠"], {"顺顺": P, "翠翠": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺"), extraction(["翠翠的父亲"], {"翠翠的父亲": D}))
    assert "翠翠的父亲" not in r.known
    assert "翠翠的父亲" not in r.canonical_aliases.get("顺顺", [])
    assert out.characters == []


def test_m16_qualified_anchor_absent_twice_no_confirm():
    """M16：翠翠的父亲 anchor 连续缺席、两 chunk 均误判 顺顺 → 不可确认。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺翠翠"), extraction(["顺顺", "翠翠"], {"顺顺": P, "翠翠": P}))
    r.resolve(make_chunk(2, text="顺顺"), extraction(["翠翠的父亲"], {"翠翠的父亲": D}))
    r.resolve(make_chunk(3, text="顺顺"), extraction(["翠翠的父亲"], {"翠翠的父亲": D}))
    assert "翠翠的父亲" not in r.known
    assert "翠翠的父亲" not in r.canonical_aliases.get("顺顺", [])


def test_m17_qualified_anchor_present_wrong_target():
    """M17：anchor ∈ candidates 但 judge 选错 → target-mismatch 不可确认。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺翠翠"), extraction(["顺顺", "翠翠"], {"顺顺": P, "翠翠": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺翠翠"), extraction(["翠翠的父亲"], {"翠翠的父亲": D}))
    assert "翠翠的父亲" not in r.known
    assert "翠翠的父亲" not in r.canonical_aliases.get("顺顺", [])


def test_m18_qualified_aligned_anchor_absent_no_alias():
    """M18：翠翠的祖父 target 对齐但 anchor 翠翠 ∉ 候选 → 不可确认。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的祖父": "祖父"}))
    r.resolve(make_chunk(1, text="翠翠祖父"), extraction(["翠翠", "祖父"], {"翠翠": P, "祖父": P}))
    out, _ = r.resolve(make_chunk(2, text="祖父"), extraction(["翠翠的祖父"], {"翠翠的祖父": D}))
    assert "翠翠的祖父" not in r.known


def test_m9_qualified_aligned_anchor_present_alias():
    """M9：翠翠的祖父 target 对齐 + anchor ∈ 候选 → 单次 alias（T-b8 回归）。"""
    r = EntityResolver(judge=judge_resolves({"翠翠的祖父": "祖父"}))
    r.resolve(make_chunk(1, text="翠翠祖父"), extraction(["翠翠", "祖父"], {"翠翠": P, "祖父": P}))
    out, _ = r.resolve(make_chunk(2, text="翠翠祖父翠翠的祖父"),
                       extraction(["翠翠的祖父"], {"翠翠的祖父": D}))
    assert r.known.get("翠翠的祖父") == "祖父"
    assert "翠翠的祖父" in r.canonical_aliases["祖父"]


def test_m19_anchor_invalid_headword_aligned_alias():
    """M19：白脸黑发的母亲（anchor 无效）→ headword 对齐 → 保持 alias（v4.1 保护）。"""
    r = EntityResolver(judge=judge_resolves({"白脸黑发的母亲": "母亲"}))
    r.resolve(make_chunk(1, text="母亲"), extraction(["母亲"], {"母亲": P}))
    out, _ = r.resolve(make_chunk(2, text="母亲白脸黑发的母亲"),
                       extraction(["白脸黑发的母亲"], {"白脸黑发的母亲": D}))
    assert r.known.get("白脸黑发的母亲") == "母亲"
    assert "白脸黑发的母亲" in r.canonical_aliases["母亲"]


def test_m20_composite_anchor_alias_in_text_alias():
    """M20：天保大老 → 大老（复合核词路径）——anchor 天保（canonical 大儿子）的别名
    「天保」在 chunk 原文 → anchor 文本在场 → 单次 alias（merge 桥接保持）。"""
    r = EntityResolver(judge=judge_resolves({"天保": "大儿子", "天保大老": "大老"}))
    r.resolve(make_chunk(1, text="大儿子和天保在河边"), extraction(["大儿子", "天保"]))
    r.resolve(make_chunk(2, text="大老在河边"), extraction(["大老"]))
    out, _ = r.resolve(make_chunk(3, text="天保大老在河边"), extraction(["天保大老"]))
    assert r.known.get("天保大老") == "大老"
    assert "天保大老" in r.canonical_aliases["大老"]


# ---------- 例外路径保持不变 ----------

def test_m10_generic_rc3_unchanged():
    """M10：哥哥→大老（GENERIC）RC3 路径不变（有候选可 alias，单次）。"""
    r = EntityResolver(judge=judge_resolves({"哥哥": "大老"}))
    r.resolve(make_chunk(1, text="大老"), extraction(["大老"], {"大老": P}))
    out, _ = r.resolve(make_chunk(2, text="大老哥哥"), extraction(["哥哥"], {"哥哥": G}))
    assert r.known.get("哥哥") == "大老"
    assert "哥哥" in r.canonical_aliases["大老"]


def test_m14_descriptive_epithet_person_kept():
    """M14：老船夫→祖父（category=PERSON）不进机制，现有单次 alias 路径。"""
    r = EntityResolver(judge=judge_resolves({"老船夫": "祖父"}))
    r.resolve(make_chunk(1, text="祖父"), extraction(["祖父"], {"祖父": P}))
    out, _ = r.resolve(make_chunk(2, text="祖父老船夫"), extraction(["老船夫"], {"老船夫": P}))
    assert r.known.get("老船夫") == "祖父"


def test_m15_category_none_keeps_status_quo():
    """M15：父亲 category=None → PERSON fallback，保持现状（不触发证据机制）。"""
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"]))   # 无 category
    assert r.known.get("父亲") == "顺顺"   # 现状：PERSON fallback + judge → alias
