"""V0.2.5-b DESCRIPTIVE/COMPOSITE canonical 时机测试（deterministic，mock extract/judge）。

覆盖 T-b1..T-b14：
- T-b1/T-b2：extraction 顺序互换后 canonical 集合一致（核心不变量）
- T-b3：ch5b 一族经 chunk 内 deferred + 单次 judge 收敛
- T-b4/5/6：无候选 / judge null / judge 缺席 → unresolved
- T-b7：judge 异常 → PERSON 兜底、GENERIC 丢弃、DESCRIPTIVE/COMPOSITE 永不 canonicalize
- T-b8/9：有候选 alias 路径不变（翠翠的祖父 / 天保大老 / 岳云二老）
- T-b10：GENERIC RC3 回归
- T-b11：judge 每 chunk 最多一次（deferred 并入同批，零额外请求）
- T-b12：unresolved 端点关系丢弃
- T-b13：PERSON 无候选立即注册（锁死）
- T-b14：unresolved 不进入 merge_evidence
"""
from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.pipeline.sections import SectionType
from app.schemas.llm import (AliasJudgeResult, ExtractionResult, MentionCategory,
                             RelationshipType)


def make_chunk(chunk_id, chapter_id=1, text="文本", section_type=SectionType.BODY):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text), section_type=section_type)


def extraction(names, categories=None, rels=None):
    chars = []
    for n in names:
        item = {"name": n}
        if categories and categories.get(n) is not None:
            item["category"] = categories[n].value
        chars.append(item)
    payload = {"characters": chars, "relationships": rels or []}
    return ExtractionResult.model_validate(payload)


def judge_null(text, pending):
    return AliasJudgeResult.model_validate(
        {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})


# ---------- T-b1 / T-b2：顺序无关（核心不变量） ----------

_SON_TEXT = "他把长子取名天保，次子取名傩送。"


def judge_son_agree(text, pending):
    return AliasJudgeResult.model_validate({
        "resolutions": [
            {"mention": p.mention, "resolves_to": "天保" if p.mention == "大儿子" else None}
            for p in pending]})


def _run_son_order(names):
    r = EntityResolver(judge=judge_son_agree)
    r.resolve(make_chunk(1, text=_SON_TEXT),
              extraction(names, {"大儿子": MentionCategory.DESCRIPTIVE,
                                 "天保": MentionCategory.PERSON}))
    return r


def test_b1_descriptive_first_then_person():
    """DESCRIPTIVE 先出现：deferred → 重召回（候选含 天保）→ 单次 judge → alias 天保。"""
    r = _run_son_order(["大儿子", "天保"])
    assert set(r.canonical_aliases) == {"天保"}
    assert r.known.get("大儿子") == "天保"
    assert r.canonical_aliases["天保"] == ["大儿子"]


def test_b2_person_first_then_descriptive():
    """PERSON 先出现：天保 立即注册，大儿子 处理期即有候选 → judge → alias。
    最终 canonical 集合与 T-b1 完全一致（顺序无关）。"""
    r = _run_son_order(["天保", "大儿子"])
    assert set(r.canonical_aliases) == {"天保"}
    assert r.known.get("大儿子") == "天保"
    assert r.canonical_aliases["天保"] == ["大儿子"]


# ---------- T-b3：ch5b 一族收敛 ----------

def judge_family(text, pending):
    # 语义正确但受候选约束：只有候选内的才可 resolves_to。
    # 次子/第二个儿子 的重召回候选仅 [天保]（傩送 尚为 pending、未入 _index）→ null → unresolved。
    mapping = {"大儿子": "天保", "长子": "天保"}
    return AliasJudgeResult.model_validate({
        "resolutions": [
            {"mention": p.mention, "resolves_to": mapping.get(p.mention)} for p in pending]})


def test_b3_ch5b_family_converges():
    """ch5b 一族（大儿子/长子/次子/第二个儿子/天保/傩送）→ 收敛 ≤2 canonical。
    大儿子/长子 → 天保 alias；次子/第二个儿子（傩送 侧、重召回候选不含 傩送）→ unresolved。"""
    names = ["大儿子", "长子", "次子", "第二个儿子", "天保", "傩送"]
    cats = {"大儿子": MentionCategory.DESCRIPTIVE, "长子": MentionCategory.DESCRIPTIVE,
            "次子": MentionCategory.DESCRIPTIVE, "第二个儿子": MentionCategory.DESCRIPTIVE,
            "天保": MentionCategory.PERSON, "傩送": MentionCategory.PERSON}
    text = "作父亲的当两个儿子很小时，就明白大儿子一切与自己相似。他把长子取名天保，次子取名傩送。"
    r = EntityResolver(judge=judge_family)
    r.resolve(make_chunk(1, text=text), extraction(names, cats))
    assert set(r.canonical_aliases) == {"天保", "傩送"}      # 一族从 6 碎片收敛到 2
    assert r.known.get("大儿子") == "天保"
    assert r.known.get("长子") == "天保"
    assert "次子" not in r.known and "第二个儿子" not in r.known   # unresolved
    assert r.hygiene_stats["descriptive_unresolved"] == 2


# ---------- T-b4 / T-b5 / T-b6：unresolved 三路 ----------

def test_b4_descriptive_no_candidate_unresolved():
    """chunk 末重召回仍无候选 → unresolved：不注册、输出剔除、计数。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["大儿子"], {"大儿子": MentionCategory.DESCRIPTIVE}))
    assert "大儿子" not in r.known
    assert out.characters == []
    assert r.hygiene_stats["descriptive_unresolved"] == 1


def test_b5_descriptive_judge_null_unresolved():
    """有候选（天保）但 judge null → unresolved。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1, text="天保"), extraction(["天保"]))
    out, _ = r.resolve(make_chunk(2, text="天保翠翠的祖父"),
                       extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert "翠翠的祖父" not in r.known
    assert "翠翠的祖父" not in r.canonical_aliases.get("天保", [])
    assert out.characters == []
    assert r.hygiene_stats["descriptive_unresolved"] == 1


def test_b6_descriptive_missing_from_judge_result_unresolved():
    """judge 结果缺席该 mention → unresolved（防御路径不得注册 DESCRIPTIVE）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({"resolutions": []})   # 全部缺席
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="天保"), extraction(["天保"]))
    out, _ = r.resolve(make_chunk(2, text="天保翠翠的祖父"),
                       extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert "翠翠的祖父" not in r.known
    assert out.characters == []
    assert r.hygiene_stats["descriptive_unresolved"] == 1


# ---------- T-b7：judge 异常分派 ----------

def test_b7_judge_exception_descriptive_never_canonicalized():
    """judge 抛错：PERSON 兜底注册；GENERIC 丢弃（D4，修复 exception 路径洞）；
    DESCRIPTIVE → unresolved，绝不 canonicalize。"""
    def j(text, pending):
        raise ValueError("judge boom")
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="天保"), extraction(["天保"]))   # seed 天保 canonical
    out, failed = r.resolve(
        make_chunk(2, text="天保"),
        extraction(["大儿子", "傩送", "哥哥"], {
            "大儿子": MentionCategory.DESCRIPTIVE,
            "傩送": MentionCategory.PERSON,
            "哥哥": MentionCategory.GENERIC,
        }))
    assert failed is True
    assert r.known.get("傩送") == "傩送"          # PERSON fail-safe 保留
    assert "大儿子" not in r.known               # DESCRIPTIVE → unresolved，永不 canonicalize
    assert "大儿子" not in r.canonical_aliases
    assert "哥哥" not in r.known                 # GENERIC → 丢弃
    assert [c.name for c in out.characters] == ["傩送"]
    assert r.hygiene_stats["descriptive_unresolved"] == 1


# ---------- T-b8 / T-b9：有候选 alias 路径不变 ----------

def test_b8_descriptive_with_candidate_alias_unchanged():
    """翠翠的祖父 有候选 祖父 → alias 路径零变化（回归）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention,
                             "resolves_to": "祖父" if p.mention == "翠翠的祖父" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="祖父翠翠"), extraction(["祖父", "翠翠"]))
    out, _ = r.resolve(make_chunk(2, text="祖父翠翠的祖父"),
                       extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert r.known.get("翠翠的祖父") == "祖父"
    assert "翠翠的祖父" in r.canonical_aliases["祖父"]
    assert r.hygiene_stats["descriptive_resolved"] == 1


def test_b9_composite_with_candidate_unchanged():
    """天保大老 / 岳云二老 有候选 → bridge judge 不变（回归）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention,
                             "resolves_to": {"天保大老": "天保", "岳云二老": "傩送"}.get(p.mention)}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="天保大老"), extraction(["天保", "大老"]))
    r.resolve(make_chunk(2, text="傩送二老"), extraction(["傩送", "二老"]))
    out, _ = r.resolve(make_chunk(3, text="天保大老傩送二老"),
                       extraction(["天保大老", "岳云二老"],
                                  {"天保大老": MentionCategory.COMPOSITE,
                                   "岳云二老": MentionCategory.COMPOSITE}))
    assert r.known.get("天保大老") == "天保"
    assert r.known.get("岳云二老") == "傩送"
    assert "岳云二老" in r.canonical_aliases["傩送"]


# ---------- T-b10：GENERIC RC3 回归 ----------

def test_b10_generic_regression_rc3():
    """GENERIC 有候选 → judge null → 丢弃（永不 canonical）；不计数 filtered（有候选）。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1, text="天保"), extraction(["天保"]))
    out, _ = r.resolve(make_chunk(2, text="天保弟弟"), extraction(["弟弟"], {"弟弟": MentionCategory.GENERIC}))
    assert "弟弟" not in r.known
    assert out.characters == []
    assert r.hygiene_stats["generic_filtered"] == 0   # 有候选不计数 filtered


# ---------- T-b11：单次 judge ----------

def test_b11_single_judge_call_with_deferred():
    """deferred 重召回并入同一批：每 chunk 只调用一次 judge（零额外请求）。"""
    calls = {"n": 0}

    def j(text, pending):
        calls["n"] += 1
        return AliasJudgeResult.model_validate({"resolutions": []})

    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text=_SON_TEXT),
              extraction(["大儿子", "长子", "天保", "傩送"], {
                  "大儿子": MentionCategory.DESCRIPTIVE, "长子": MentionCategory.DESCRIPTIVE,
                  "天保": MentionCategory.PERSON, "傩送": MentionCategory.PERSON}))
    assert calls["n"] == 1


# ---------- T-b12：unresolved 端点关系丢弃 ----------

def test_b12_unresolved_relation_endpoint_dropped():
    rels = [{"source": "大儿子", "target": "顺顺", "type": "family", "confidence": 0.9}]
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(
        make_chunk(1, text="大儿子顺顺"),
        extraction(["大儿子", "顺顺"], {"大儿子": MentionCategory.DESCRIPTIVE,
                                      "顺顺": MentionCategory.PERSON}, rels=rels))
    assert out.relationships == []
    assert "大儿子" not in r.known
    assert r.known.get("顺顺") == "顺顺"


# ---------- T-b13：PERSON 无候选立即注册 ----------

def test_b13_person_no_candidate_immediate_register():
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["傩送"], {"傩送": MentionCategory.PERSON}))
    assert r.known.get("傩送") == "傩送"
    assert r._deferred == []
    assert out.characters[0].name == "傩送"


# ---------- T-b14：unresolved 不入 merge_evidence ----------

def test_b14_unresolved_not_in_merge_evidence():
    """大儿子 有 ≥2 候选（天保/大老）本会生成 bridge evidence；unresolved 后证据必须被清除。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({"resolutions": []})   # 全部 null/缺席 → unresolved
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="天保大老"), extraction(["天保", "大老"]))   # 两个 established canonical
    r.resolve(make_chunk(2, text="天保大老大儿子"), extraction(["大儿子"], {"大儿子": MentionCategory.DESCRIPTIVE}))
    assert "大儿子" not in r.known
    assert all("大儿子" not in ev["mention"] and "大儿子" not in ev["pair"]
               for ev in r.merge_evidence)
