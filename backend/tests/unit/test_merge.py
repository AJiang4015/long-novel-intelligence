"""V0.2.3-b1 canonical merge decision 测试（mock merge judge，不调真实 LLM）。"""
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MergeJudgeResult


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


class _AliasJudge:
    """mock alias judge：mapping = {mention -> canonical | None}。"""

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def __call__(self, text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [
                {"mention": p.mention, "resolves_to": self.mapping.get(p.mention)}
                for p in pending
            ],
        })


class _MergeJudge:
    """mock merge judge：mapping = {(a,b) frozenset -> bool}；可配置失败。"""

    def __init__(self, mapping=None, failure=None, confidence=0.9):
        self.mapping = mapping or {}
        self.failure = failure  # 抛出的异常，模拟 judge 失败
        self.confidence = confidence
        self.calls = 0
        self.last_input = None

    def __call__(self, pairs):
        self.calls += 1
        self.last_input = pairs
        if self.failure is not None:
            raise self.failure
        merges = []
        for p in pairs:
            key = frozenset((p.a.canonical, p.b.canonical))
            merge = self.mapping.get(key, False)
            merges.append({"a": p.a.canonical, "b": p.b.canonical,
                           "merge": merge, "confidence": self.confidence})
        return MergeJudgeResult.model_validate({"merges": merges})


def build_two_canonicals(r, chunk_ids, names):
    """依次 resolve 若干 chunk 确立 canonical；返回 established 快照后的 resolver。"""
    for cid, name in zip(chunk_ids, names):
        r.resolve(make_chunk(cid, text=f"{name}在河边"), extraction([name]))
    return r


# 1. A/B 同人 → merge_map 产生 merge
def test_same_person_merges():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [6, 9], ["大儿子", "大老"])
    judge = _MergeJudge(mapping={frozenset(("大儿子", "大老")): True})
    # 手动注入 bridge evidence（chunk 11 mention 天保大老）
    r.merge_evidence.append({
        "mention": "天保大老", "candidates": ["大儿子", "大老"],
        "pair": ["大儿子", "大老"], "chunk_id": 11, "chapter_id": 3,
        "text": "天保大老过溪",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {"大老": "大儿子"}   # first_seen 6 < 9 → 大儿子 keep
    assert out["stats"]["entity_resolution"]["merged_pairs"] == 1


# 2. A/B 不同人 → 不 merge
def test_different_persons_not_merged():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["翠翠", "傩送"])
    judge = _MergeJudge(mapping={frozenset(("翠翠", "傩送")): False})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["翠翠", "傩送"],
        "pair": ["翠翠", "傩送"], "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {}
    assert out["stats"]["entity_resolution"]["rejected_pairs"] == 1


# 3. bridge mention 双侧命中 → 产生 pair（resolve 过程中自动收集）
def test_bridge_mention_generates_pair():
    # 模拟真实《边城》：chunk6 大儿子 成为 canonical，天保 并入大儿子（alias）
    r = EntityResolver(judge=_AliasJudge({"天保": "大儿子"}))
    r.resolve(make_chunk(6, text="他把长子取名天保"), extraction(["大儿子", "天保"]))
    r.resolve(make_chunk(9, text="大老在河边"), extraction(["大老"]))
    # chunk 11：提取 大老（known）+ 天保大老（未知）；原文含 天保（大儿子 的 alias）→ text confirmed 命中大儿子
    r.resolve(make_chunk(11, text="天保大老在河边"), extraction(["大老", "天保大老"]))
    assert len(r.merge_evidence) >= 1
    ev = r.merge_evidence[0]
    assert ev["mention"] == "天保大老"
    assert set(ev["pair"]) == {"大儿子", "大老"}
    assert ev["chunk_id"] == 11
    assert "text" in ev and ev["text"]


# 4. pair 去重（同 pair 只判一次）
def test_pair_dedup():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True})
    for i in range(3):
        r.merge_evidence.append({
            "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
            "chunk_id": 10 + i, "chapter_id": 1, "text": f"e{i}",
        })
    out = r.decide_merges(judge)
    assert judge.calls == 1            # 一次批量判定
    assert out["merge_map"] == {"B": "A"}
    assert len(judge.last_input) == 1  # pair 去重后只有 1 个输入


# 5. judge failure → 不 merge，不抛异常
def test_judge_failure_no_merge():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(failure=RuntimeError("http_429"))
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {}
    stats = out["stats"]["entity_resolution"]
    assert stats["failed_pairs"] == 1
    assert len(out["merge_failures"]) == 1


# 6. confidence 低于可配置阈值 → 不 merge
def test_low_confidence_not_merged():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True}, confidence=0.3)
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge, confidence_threshold=0.5)
    assert out["merge_map"] == {}
    assert out["stats"]["entity_resolution"]["rejected_pairs"] == 1


# 7. first_seen 更早者成为 keep
def test_first_seen_earlier_is_keep():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [9, 6], ["B", "A"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 11, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {"B": "A"}   # A first_seen 6 < B first_seen 9 → A keep


# 8. A/B 已通过 merge_map 合并 → 不重复生成 pair（同一 pair 幂等）
def test_existing_merge_not_duplicated():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    r.decide_merges(judge)
    r.merge_evidence.append({
        "mention": "桥2", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 4, "chapter_id": 1, "text": "y",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {"B": "A"}   # 结果幂等


# 9. 不做全局 O(N²) comparison（构造 >100 canonical 仍线性/可用）
def test_many_canonicals_no_o2():
    r = EntityResolver(judge=judge_null)
    for i in range(1, 101):
        r.resolve(make_chunk(i, text=f"人物{i}在河边"), extraction([f"人物{i}"]))
    # 注入 1 个桥接 evidence → 只判 1 个 pair，不触发全量比较
    judge = _MergeJudge(mapping={frozenset(("人物1", "人物2")): True})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["人物1", "人物2"], "pair": ["人物1", "人物2"],
        "chunk_id": 101, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert judge.calls == 1
    assert len(judge.last_input) == 1


# 10. b1 纯 decision 锁死：known/_index/canonical_aliases 快照不变
def test_b1_pure_decision_no_state_mutation():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    before = (dict(r.known), {k: set(v) for k, v in r._index.items()},
              {k: list(v) for k, v in r.canonical_aliases.items()})
    r.decide_merges(_MergeJudge(mapping={frozenset(("A", "B")): True}))
    after = (dict(r.known), {k: set(v) for k, v in r._index.items()},
             {k: list(v) for k, v in r.canonical_aliases.items()})
    assert before == after


# 11. merge_evidence 完整结构 + 3 canonical 命中生成 3 条
def test_merge_evidence_structure_and_3way_pairs():
    # 三个 established canonical：A（含 alias a1）、B、C
    r = EntityResolver(judge=_AliasJudge({"a1": "A"}))
    r.resolve(make_chunk(1, text="A在河边"), extraction(["A", "a1"]))
    r.resolve(make_chunk(2, text="B在河边"), extraction(["B"]))
    r.resolve(make_chunk(3, text="C在河边"), extraction(["C"]))
    # chunk 4：提取 B/C（known）+ 桥（未知），原文含 a1（A 的 alias）→ text confirmed 命中 A
    # 桥 的候选同时含 A/B/C（established）→ 生成 3 条 pair evidence
    r.resolve(make_chunk(4, text="a1和B还有C都在河边"), extraction(["B", "C", "桥"]))
    pairs = {frozenset(ev["pair"]) for ev in r.merge_evidence}
    assert len(r.merge_evidence) == 3          # (A,B)(A,C)(B,C)
    assert frozenset(("A", "B")) in pairs
    assert frozenset(("A", "C")) in pairs
    assert frozenset(("B", "C")) in pairs
    ev = r.merge_evidence[0]
    assert set(ev) >= {"mention", "candidates", "pair", "chunk_id", "chapter_id", "text"}
    assert ev["chunk_id"] == 4
