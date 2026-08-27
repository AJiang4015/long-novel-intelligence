"""V0.2.5-a context-aware ER 测试（deterministic，mock extract/judge，不调真实 LLM）。

覆盖 T-a1..T-a10、T-a14（T-a11/12/13 在 test_sections.py）。
"""
from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.pipeline.sections import SectionType
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MentionCategory


def make_chunk(chunk_id, chapter_id=1, text="文本", section_type=SectionType.BODY):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text), section_type=section_type)


def extraction(names, categories=None):
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


# ---- T-a1：EPIGRAPH 父亲（DESCRIPTIVE 无候选）不注册 ----

def test_epigraph_descriptive_no_candidate_not_canonical():
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1, section_type=SectionType.EPIGRAPH),
                       extraction(["父亲"], {"父亲": MentionCategory.DESCRIPTIVE}))
    assert "父亲" not in r.known
    assert out.characters == []
    assert r.hygiene_stats["nonbody_descriptive_dropped"] == 1


# ---- T-a2（V0.2.5-b 取代）：BODY 父亲 无候选 → deferred → unresolved ----

def test_body_descriptive_no_candidate_deferred_unresolved():
    """V0.2.5-b 取代 -a T-a2 旧期望：BODY DESCRIPTIVE 无候选 → deferred → unresolved。
    （-a spec T-a2「照旧注册 canonical」被 -b D2 有意取代；BODY PERSON 无候选不受影响，见 T-a8）"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["父亲"], {"父亲": MentionCategory.DESCRIPTIVE}))
    assert "父亲" not in r.known
    assert out.characters == []
    assert r.hygiene_stats["descriptive_unresolved"] == 1


# ---- T-a3：EPIGRAPH 兄弟（GENERIC）丢弃 ----

def test_epigraph_generic_dropped():
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1, section_type=SectionType.EPIGRAPH),
              extraction(["兄弟"], {"兄弟": MentionCategory.GENERIC}))
    assert "兄弟" not in r.known
    assert r.hygiene_stats["generic_filtered"] == 1


# ---- T-a4：BODY 兄弟 有候选 → alias 而非 canonical（RC3 回归）----

def test_body_generic_with_candidate_alias_only():
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "天保" if p.mention == "兄弟" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="天保兄弟"), extraction(["天保"]))
    out, _ = r.resolve(make_chunk(2, text="天保兄弟"), extraction(["兄弟"], {"兄弟": MentionCategory.GENERIC}))
    assert r.known.get("兄弟") == "天保"
    assert "兄弟" in r.canonical_aliases["天保"]
    assert "兄弟" not in r.canonical_aliases   # 永不 canonical


# ---- T-a5：EPIGRAPH 兆和（PERSON）→ provisional，保留在输出 ----

def test_epigraph_person_provisional_in_output():
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1, section_type=SectionType.EPIGRAPH),
                       extraction(["兆和"], {"兆和": MentionCategory.PERSON}))
    assert out.characters[0].name == "兆和"      # 不被误删
    assert r.known.get("兆和") == "兆和"
    assert "兆和" in r._provisional
    assert "兆和" not in r._index                    # 候选源不可见
    assert r.hygiene_stats["nonbody_person_provisional"] == 1


# ---- T-a6：flush 未确认 → 不入图 + 计数 ----

def test_flush_unconfirmed_provisional_dropped():
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1, section_type=SectionType.EPIGRAPH),
              extraction(["兆和"], {"兆和": MentionCategory.PERSON}))
    dropped = r.finalize()
    assert dropped == {"兆和"}
    assert "兆和" not in r.known
    assert "兆和" not in r.canonical_aliases
    assert r.hygiene_stats["nonbody_provisional_dropped"] == 1


# ---- T-a7：祖父 epigraph provisional → BODY 同名字晋升；mc/chapters 只计 BODY ----

def test_provisional_promoted_on_body_occurrence():
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1, chapter_id=1, section_type=SectionType.EPIGRAPH),
              extraction(["祖父"], {"祖父": MentionCategory.PERSON}))
    assert "祖父" in r._provisional
    out, _ = r.resolve(make_chunk(2, chapter_id=2, section_type=SectionType.BODY, text="祖父撑船"),
                       extraction(["祖父"], {"祖父": MentionCategory.PERSON}))
    assert "祖父" not in r._provisional
    assert "祖父" in r._index
    assert r._canonical_chapters.get("祖父") == {2}    # 非正文 ch1 不参与
    assert r._canonical_chunks.get("祖父") == {2}
    assert r._first_seen.get("祖父") == 2              # 首次 BODY 证据为准


# ---- T-a8：section_type=BODY 不影响正常 canonical ----

def test_body_section_does_not_change_normal_canonical():
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1, section_type=SectionType.BODY),
                       extraction(["傩送"], {"傩送": MentionCategory.PERSON}))
    assert r.known.get("傩送") == "傩送"
    assert "傩送" not in r._provisional
    assert "傩送" in r._index
    assert r.hygiene_stats["nonbody_person_provisional"] == 0


# ---- T-a9：非正文关系端点未确认 → 关系丢弃（graph 过滤层）----

def test_nonbody_relation_endpoints_dropped():
    from app.pipeline.merger import (MergedGraph, PersonAgg, RelAgg,
                                     drop_unconfirmed_entities)
    from app.schemas.llm import RelationshipType
    graph = MergedGraph(
        persons={
            "沈从文": PersonAgg(name="沈从文", mention_count=1, chapters={1}),
            "祖父": PersonAgg(name="祖父", mention_count=2, chapters={1, 4}),
            "翠翠": PersonAgg(name="翠翠", mention_count=1, chapters={4}),
        },
        relationships={
            ("沈从文", "祖父", RelationshipType.family): RelAgg(
                source="沈从文", target="祖父", type=RelationshipType.family,
                chunk_ids={1}, confidences=[0.95]),
            ("翠翠", "祖父", RelationshipType.family): RelAgg(
                source="翠翠", target="祖父", type=RelationshipType.family,
                chunk_ids={4}, confidences=[0.9]),
        },
    )
    out = drop_unconfirmed_entities(graph, {"沈从文"})
    assert "沈从文" not in out.persons
    assert ("沈从文", "祖父", RelationshipType.family) not in out.relationships
    assert ("翠翠", "祖父", RelationshipType.family) in out.relationships
    assert "祖父" in out.persons


def test_drop_unconfirmed_entities_empty_noop():
    from app.pipeline.merger import MergedGraph, drop_unconfirmed_entities
    graph = MergedGraph()
    assert drop_unconfirmed_entities(graph, set()) is graph


# ---- T-a10：RC2 回归（EPIGRAPH 中 COLLECTIVE 仍硬过滤）----

def test_rc2_hard_filter_in_epigraph():
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1, section_type=SectionType.EPIGRAPH),
              extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert "两个儿子" not in r.known
    assert r.hygiene_stats["collective_filtered"] == 1


# ---- T-a14：provisional 不得进入 BODY recall candidate source ----

def test_provisional_never_in_body_recall_candidate_source():
    seen = {"cands": []}

    def j(text, pending):
        seen["cands"] = [[c.canonical for c in p.candidates] for p in pending]
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})

    r = EntityResolver(judge=j)
    # ch1 EPIGRAPH：兆和 PERSON → provisional
    r.resolve(make_chunk(1, section_type=SectionType.EPIGRAPH),
              extraction(["兆和"], {"兆和": MentionCategory.PERSON}))
    assert "兆和" in r._provisional and "兆和" not in r._index
    # ch2 BODY：原文含「兆和」子串 + 提取 翠翠（无其他已知）→ 兆和 不得成为候选源
    r.resolve(make_chunk(2, section_type=SectionType.BODY, text="兆和在这里"),
              extraction(["翠翠"], {"翠翠": MentionCategory.PERSON}))
    assert "兆和" not in r._index
    assert r._text_mentions("兆和在这里") == set()
    assert seen["cands"] == []                        # 翠翠 无候选（兆和 不可见）
    # ch3 BODY：同名字出现 → 晋升
    r.resolve(make_chunk(3, section_type=SectionType.BODY, text="兆和又出现"),
              extraction(["兆和"], {"兆和": MentionCategory.PERSON}))
    assert "兆和" not in r._provisional and "兆和" in r._index
    # ch4 BODY：顺顺 的候选应包含 兆和（晋升后可见）
    r.resolve(make_chunk(4, section_type=SectionType.BODY, text="兆和顺顺"),
              extraction(["顺顺"], {"顺顺": MentionCategory.PERSON}))
    assert seen["cands"] and "兆和" in seen["cands"][-1]
