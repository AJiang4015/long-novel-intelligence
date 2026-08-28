"""P20 checks.py 纯函数单测（全 mock 数据，无网络/Neo4j/LLM，TESTING.md §2）。

覆盖（Spec §4.3/§5.2/§7.1 + §12.1 测试矩阵）：
- checkset v1 结构校验（validate_checkset）；
- 各检查 kind 的判定分类（PASS/FAIL/OBSERVATION/INCONCLUSIVE/SKIP）；
- 空洞 PASS 防（前置条件不满足 → SKIP）；
- G4 降级（失败 chunk → needs_full_corpus 决定性检查 INCONCLUSIVE；记录型检查不降级）；
- 冻结语义编码（C5/D2/E1/F1 记录不判败；attribution/layer 齐全）。
"""

from __future__ import annotations

import pytest

from tools.eval_framework.checks import (
    CHECKSET_V1,
    CheckDef,
    CheckOutcome,
    CheckSet,
    DECISIVE_OUTCOMES,
    OUTCOME_FAIL,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_OBSERVATION,
    OUTCOME_PASS,
    OUTCOME_SKIP,
    evaluate_check,
    evaluate_checkset,
    validate_checkset,
)


# ---------------------------------------------------------------------------
# 测试数据辅助
# ---------------------------------------------------------------------------


def person(name: str, aliases=(), mention_count: int = 1, chapters=(), chunk_ids=()):
    return {"name": name, "aliases": list(aliases), "mention_count": mention_count,
            "chapters": list(chapters), "chunk_ids": list(chunk_ids)}


def snapshot(persons=(), *, novel_id: str = "novel-1", labels_used=("Novel", "Person"),
             novel_ids_seen=None, alias_search=None, counts=None,
             checkpoint_dir_exists: bool = False):
    return {
        "novel_id": novel_id,
        "persons": list(persons),
        "relationships": [],
        "labels_used": list(labels_used) if labels_used is not None else None,
        "novel_ids_seen": list(novel_ids_seen) if novel_ids_seen is not None else [novel_id],
        "alias_search": alias_search or {},
        "counts": counts or {},
        "checkpoint_dir_exists": checkpoint_dir_exists,
    }


def stats(*, failed_blocks=(), hygiene=None, merge=None, counts=None):
    return {
        "job_status": "completed_with_errors" if failed_blocks else "completed",
        "failed_blocks": list(failed_blocks),
        "counts": counts or {"persons": 0, "relationships": 0},
        "hygiene": hygiene or {},
        "merge": merge or {},
    }


def outcome_for(check_id: str, snapshot: dict, st: dict) -> CheckOutcome:
    check = CHECKSET_V1.by_id(check_id)
    assert check is not None, f"checkset 缺检查 {check_id}"
    return evaluate_checkset(CHECKSET_V1, snapshot, st)[CHECKSET_V1.checks.index(check)]


# ---------------------------------------------------------------------------
# checkset 结构
# ---------------------------------------------------------------------------


def test_checkset_v1_valid_and_complete():
    assert validate_checkset(CHECKSET_V1) == []
    ids = [c.id for c in CHECKSET_V1.checks]
    # Spec §4.2 检查清单 21 条（A6+B2+C5+D3+D2+E1+F1+G4+... 全量）
    assert ids == ["A1", "A2", "A3", "A4", "A5", "A6",
                   "B1", "B2",
                   "C1", "C2", "C3", "C4", "C5",
                   "D1", "D2", "D3",
                   "E1",
                   "F1",
                   "G1", "G2", "G3", "G4", "G5"]


def test_checkset_v1_every_check_has_attribution_and_layer():
    for c in CHECKSET_V1.checks:
        assert c.attribution, f"[{c.id}] 缺 attribution"
        assert c.layer, f"[{c.id}] 缺 layer"
        assert c.group


def test_checkset_v1_corpus_pinned():
    assert CHECKSET_V1.corpus["name"] == "边城"
    assert len(CHECKSET_V1.corpus["content_hash"]) == 64  # sha256 hex


def test_validate_checkset_detects_problems():
    bad = CheckDef("X1", "g", "d", {"kind": "no_such_kind"}, attribution="a", layer="l")
    assert validate_checkset(CheckSet(1, "1", "t", {}, (bad,))) != []

    dup = [CheckDef("X1", "g", "d", {"kind": "count_eq", "key": "k", "expected": 0},
                    attribution="a", layer="l")] * 2
    errs = validate_checkset(CheckSet(1, "1", "t", {}, tuple(dup)))
    assert any("重复" in e for e in errs)

    no_attr = CheckDef("X2", "g", "d", {"kind": "count_eq", "key": "k", "expected": 0}, layer="l")
    assert any("attribution" in e for e in validate_checkset(CheckSet(1, "1", "t", {}, (no_attr,))))

    bad_class = CheckDef("X3", "g", "d", {"kind": "count_eq", "key": "k", "expected": 0},
                         attribution="a", layer="l", outcome_class="bogus")
    assert any("outcome_class" in e for e in validate_checkset(CheckSet(1, "1", "t", {}, (bad_class,))))

    bad_pre = CheckDef("X4", "g", "d", {"kind": "count_eq", "key": "k", "expected": 0},
                       attribution="a", layer="l", preconditions=("stat_exists:x",))
    assert any("前置条件" in e for e in validate_checkset(CheckSet(1, "1", "t", {}, (bad_pre,))))


def test_checkdef_unknown_kind_caught_by_validation():
    # 构造不校验（单一校验入口 validate_checkset）；未知 kind 必须被 schema 校验拦截
    bad = CheckDef("X1", "g", "d", {"kind": "no_such_kind"}, attribution="a", layer="l")
    assert any("未知 kind" in e for e in validate_checkset(CheckSet(1, "1", "t", {}, (bad,))))


# ---------------------------------------------------------------------------
# A 正向合并（TESTING.md §4）
# ---------------------------------------------------------------------------


def test_A1_merge_ok():
    snap = snapshot([person("傩送", aliases=["二老", "老二"])])
    assert outcome_for("A1", snap, stats()).outcome == OUTCOME_PASS


def test_A1_split_fails():
    snap = snapshot([person("傩送"), person("二老")])
    out = outcome_for("A1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["canonicals"] == ["二老", "傩送"]


def test_A1_missing_alias_fails():
    snap = snapshot([person("傩送", aliases=["二老"])])
    out = outcome_for("A1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["canonical"] == "傩送"


def test_A1_no_member_skips():
    snap = snapshot([person("翠翠")])
    assert outcome_for("A1", snap, stats()).outcome == OUTCOME_SKIP


def test_A2_merge_ok_and_split_fails():
    assert outcome_for("A2", snapshot([person("天保", aliases=["大老"])]), stats()).outcome == OUTCOME_PASS
    out = outcome_for("A2", snapshot([person("天保"), person("大老")]), stats())
    assert out.outcome == OUTCOME_FAIL


def test_A3_absorbed_ok():
    assert outcome_for("A3", snapshot([person("祖父", aliases=["老船夫"])]), stats()).outcome == OUTCOME_PASS


def test_A3_fragment_person_fails():
    out = outcome_for("A3", snapshot([person("祖父"), person("老船夫")]), stats())
    assert out.outcome == OUTCOME_FAIL
    assert "独立 canonical" in out.reason


def test_A3_not_absorbed_fails_and_target_missing_skips():
    out = outcome_for("A3", snapshot([person("祖父")]), stats())
    assert out.outcome == OUTCOME_FAIL
    assert outcome_for("A3", snapshot([person("翠翠")]), stats()).outcome == OUTCOME_SKIP


def test_A4_aliased_into_爷爷():
    assert outcome_for("A4", snapshot([person("祖父", aliases=["爷爷"])]), stats()).outcome == OUTCOME_PASS
    assert outcome_for("A4", snapshot([person("祖父")]), stats()).outcome == OUTCOME_FAIL


def test_A5_negative_distinct_ok():
    snap = snapshot([person("傩送"), person("杨马兵")])
    assert outcome_for("A5", snap, stats()).outcome == OUTCOME_PASS


def test_A5_negative_merged_fails():
    snap = snapshot([person("傩送", aliases=["杨马兵"])])
    out = outcome_for("A5", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert "误合并" in out.reason


def test_A5_partial_extraction_skips():
    snap = snapshot([person("傩送")])
    assert outcome_for("A5", snap, stats()).outcome == OUTCOME_SKIP


def test_A6_search_unique_ok():
    snap = snapshot([person("傩送", aliases=["二老"])],
                    alias_search={"二老": {"hits": [{"name": "傩送", "aliases": ["二老"]}]}})
    assert outcome_for("A6", snap, stats()).outcome == OUTCOME_PASS


def test_A6_search_failures():
    base = {"二老": {"hits": []}}
    assert outcome_for("A6", snapshot(alias_search=base), stats()).outcome == OUTCOME_FAIL
    multi = {"二老": {"hits": [{"name": "傩送"}, {"name": "天保"}]}}
    out = outcome_for("A6", snapshot(alias_search=multi), stats())
    assert out.outcome == OUTCOME_FAIL
    wrong = {"二老": {"hits": [{"name": "二老"}]}}
    assert outcome_for("A6", snapshot(alias_search=wrong), stats()).outcome == OUTCOME_FAIL


def test_A6_missing_data_skips():
    assert outcome_for("A6", snapshot(), stats()).outcome == OUTCOME_SKIP


# ---------------------------------------------------------------------------
# B 非正文（P016）
# ---------------------------------------------------------------------------


def test_B1_nonbody_zero_ok():
    snap = snapshot(counts={"nonbody_canonical_count": 0})
    assert outcome_for("B1", snap, stats()).outcome == OUTCOME_PASS


def test_B1_nonbody_positive_fails():
    snap = snapshot(counts={"nonbody_canonical_count": 2})
    out = outcome_for("B1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["value"] == 2


def test_B1_missing_count_skips():
    assert outcome_for("B1", snapshot(), stats()).outcome == OUTCOME_SKIP


def test_B2_records_provisional_counts():
    st = stats(hygiene={"nonbody_person_provisional": 3, "nonbody_provisional_dropped": 3,
                        "nonbody_descriptive_dropped": 0})
    out = outcome_for("B2", snapshot(), st)
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["hygiene.nonbody_person_provisional"] == 3


def test_B2_missing_all_keys_skips():
    assert outcome_for("B2", snapshot(), stats()).outcome == OUTCOME_SKIP


# ---------------------------------------------------------------------------
# C P16-b / P18 冻结（D-5 / D-6）
# ---------------------------------------------------------------------------


def test_C1_father_absent_pass():
    snap = snapshot([person("顺顺")])
    assert outcome_for("C1", snap, stats()).outcome == OUTCOME_PASS


def test_C1_father_person_fails():
    snap = snapshot([person("顺顺"), person("父亲")])
    out = outcome_for("C1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["person"] == "父亲"


def test_C1_father_absorbed_fails():
    snap = snapshot([person("顺顺", aliases=["父亲"])])
    out = outcome_for("C1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["absorbed_into"] == ["顺顺"]


def test_C1_vacuous_guard_without_顺顺():
    # 顺顺 未被提取 → 前置不满足 → SKIP（禁止空洞 PASS）
    snap = snapshot([person("翠翠")])
    assert outcome_for("C1", snap, stats()).outcome == OUTCOME_SKIP


def test_C2_qualified_interception():
    snap = snapshot([person("翠翠")])
    assert outcome_for("C2", snap, stats()).outcome == OUTCOME_PASS
    snap2 = snapshot([person("翠翠"), person("顺顺", aliases=["翠翠的父亲"])])
    out = outcome_for("C2", snap2, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["absorbed_into"] == ["顺顺"]


def test_C2_or_precondition():
    # 翠翠 与 翠翠的父亲 都未提取 → SKIP
    assert outcome_for("C2", snapshot([person("顺顺")]), stats()).outcome == OUTCOME_SKIP


def test_C3_daddy_confirmed():
    snap = snapshot([person("顺顺", aliases=["爹爹"])])
    assert outcome_for("C3", snap, stats()).outcome == OUTCOME_PASS
    snap2 = snapshot([person("顺顺")])
    assert outcome_for("C3", snap2, stats()).outcome == OUTCOME_FAIL


def test_C4_sink_containment():
    snap = snapshot([person("顺顺", aliases=["船总顺顺", "中年人"])])
    assert outcome_for("C4", snap, stats()).outcome == OUTCOME_PASS
    snap2 = snapshot([person("顺顺", aliases=["爸爸"])])
    out = outcome_for("C4", snap2, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["forbidden_hits"] == ["爸爸"]


def test_C5_observation_not_fail():
    # 爸爸 独立 Person → OBSERVATION（D5 Known Limitation，记录不判败）
    snap = snapshot([person("爸爸")])
    out = outcome_for("C5", snap, stats())
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["person"] is True
    # 爸爸 未注册 → 同样 OBSERVATION（记录事实）
    out2 = outcome_for("C5", snapshot([person("顺顺")]), stats())
    assert out2.outcome == OUTCOME_OBSERVATION
    assert out2.actual["person"] is False


# ---------------------------------------------------------------------------
# D P17 / D-9
# ---------------------------------------------------------------------------


def test_D1_family_converged_ok():
    snap = snapshot([person("天保", aliases=["大儿子", "长子", "次子"]), person("傩送")])
    assert outcome_for("D1", snap, stats()).outcome == OUTCOME_PASS


def test_D1_independent_fragment_fails():
    snap = snapshot([person("天保"), person("大儿子")])
    out = outcome_for("D1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["fragments"][0]["kind"] == "independent"


def test_D1_wrong_absorption_fails():
    snap = snapshot([person("天保"), person("顺顺", aliases=["长子"])])
    out = outcome_for("D1", snap, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["fragments"][0]["kind"] == "wrong_absorption"


def test_D1_no_family_skips():
    snap = snapshot([person("翠翠"), person("大儿子")])
    assert outcome_for("D1", snap, stats()).outcome == OUTCOME_SKIP


def test_D2_records_descriptive_stats():
    st = stats(hygiene={"descriptive_resolved": 3, "descriptive_unresolved": 19,
                        "composite_resolved": 5, "composite_unresolved": 0})
    out = outcome_for("D2", snapshot(), st)
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["hygiene.descriptive_unresolved"] == 19


def test_D3_fragments_not_independent():
    snap = snapshot([person("天保", aliases=["长子"])])
    assert outcome_for("D3", snap, stats()).outcome == OUTCOME_PASS
    snap2 = snapshot([person("次子")])
    out = outcome_for("D3", snap2, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["fragments"] == ["次子"]


# ---------------------------------------------------------------------------
# E / F
# ---------------------------------------------------------------------------


def test_E1_records_hygiene_stats():
    st = stats(hygiene={"collective_filtered": 1, "generic_filtered": 11, "invalid_filtered": 0})
    out = outcome_for("E1", snapshot(), st)
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["hygiene.generic_filtered"] == 11


def test_F1_merge_all_failed_inconclusive():
    st = stats(merge={"merge_candidate_pairs": 148, "merged_pairs": 0,
                      "rejected_pairs": 0, "low_confidence_pairs": 0, "failed_pairs": 148})
    out = outcome_for("F1", snapshot(), st)
    assert out.outcome == OUTCOME_INCONCLUSIVE
    assert "INCONCLUSIVE" in out.reason


def test_F1_merge_partial_observation():
    st = stats(merge={"merge_candidate_pairs": 10, "merged_pairs": 3,
                      "rejected_pairs": 5, "low_confidence_pairs": 2, "failed_pairs": 0})
    out = outcome_for("F1", snapshot(), st)
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["merged_pairs"] == 3


def test_F1_missing_merge_skips():
    st = stats()
    del st["merge"]  # 契约要求 runner 始终提供；缺失 = 数据不完整 → SKIP
    assert outcome_for("F1", snapshot(), st).outcome == OUTCOME_SKIP


# ---------------------------------------------------------------------------
# G 数据安全与图完整性
# ---------------------------------------------------------------------------


def test_G1_labels_subset_ok_and_fail():
    assert outcome_for("G1", snapshot(labels_used=["Novel", "Person"]), stats()).outcome == OUTCOME_PASS
    out = outcome_for("G1", snapshot(labels_used=["Novel", "Person", "Disease"]), stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["labels"] == ["Disease", "Novel", "Person"]
    assert outcome_for("G1", snapshot(labels_used=None), stats()).outcome == OUTCOME_SKIP


def test_G2_records_counts():
    st = stats(counts={"persons": 50, "relationships": 56})
    out = outcome_for("G2", snapshot(), st)
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["counts.persons"] == 50


def test_G3_novel_isolation():
    snap = snapshot(novel_id="novel-1", novel_ids_seen=["novel-1", "novel-1"])
    assert outcome_for("G3", snap, stats()).outcome == OUTCOME_PASS
    snap2 = snapshot(novel_id="novel-1", novel_ids_seen=["novel-1", "other-novel"])
    out = outcome_for("G3", snap2, stats())
    assert out.outcome == OUTCOME_FAIL
    assert out.actual["seen"] == ["novel-1", "other-novel"]


def test_G4_records_failed_blocks():
    st = stats(failed_blocks=[{"chunk_id": 13, "chapter_id": 12, "error": "ReadTimeout"}])
    out = outcome_for("G4", snapshot(), st)
    assert out.outcome == OUTCOME_OBSERVATION
    assert out.actual["failed_blocks"] == st["failed_blocks"]


def test_G5_checkpoint_guard():
    assert outcome_for("G5", snapshot(checkpoint_dir_exists=False), stats()).outcome == OUTCOME_PASS
    out = outcome_for("G5", snapshot(checkpoint_dir_exists=True), stats())
    assert out.outcome == OUTCOME_FAIL
    assert "checkpoint" in out.reason


# ---------------------------------------------------------------------------
# G4 降级规则（Spec §4.2 G4 / §7.1）
# ---------------------------------------------------------------------------


def test_g4_degrades_needs_full_corpus_checks():
    snap = snapshot([person("傩送", aliases=["二老"]), person("顺顺")])
    st = stats(failed_blocks=[{"chunk_id": 3, "chapter_id": 3, "error": "x"}])
    outcomes = evaluate_checkset(CHECKSET_V1, snap, st)
    by_id = {o.check_id: o for o in outcomes}
    # A1（needs_full_corpus）→ INCONCLUSIVE（即使快照满足合并）
    assert by_id["A1"].outcome == OUTCOME_INCONCLUSIVE
    assert "G4" in by_id["A1"].reason
    # C1（needs_full_corpus=False）→ 正常判定（PASS）
    assert by_id["C1"].outcome == OUTCOME_PASS
    # 记录型（C5/F1）不被 G4 降级
    assert by_id["C5"].outcome == OUTCOME_OBSERVATION


def test_g4_no_failed_chunks_no_degradation():
    snap = snapshot([person("傩送", aliases=["二老", "老二"])])
    outcomes = evaluate_checkset(CHECKSET_V1, snap, stats())
    assert {o.check_id: o.outcome for o in outcomes}["A1"] == OUTCOME_PASS


def test_g4_skips_vacuous_before_degradation():
    """无失败 chunk 时，前置不满足 → SKIP（空洞防优先于判定）。"""
    snap = snapshot([person("翠翠")])  # 无 顺顺
    out = outcome_for("C1", snap, stats())
    assert out.outcome == OUTCOME_SKIP


# ---------------------------------------------------------------------------
# 判定原子性（evaluate_check 直连；outcome 契约）
# ---------------------------------------------------------------------------


def test_evaluate_check_respects_preconditions_directly():
    check = CHECKSET_V1.by_id("C1")
    assert evaluate_check(check, snapshot([person("翠翠")]), stats()).outcome == OUTCOME_SKIP
    assert evaluate_check(check, snapshot([person("顺顺")]), stats()).outcome == OUTCOME_PASS


def test_decisive_outcomes_contract():
    # 只有 PASS/FAIL 是决定性结果（baseline stable/variance 分类的输入，Spec §4.3）
    assert set(DECISIVE_OUTCOMES) == {OUTCOME_PASS, OUTCOME_FAIL}


def test_record_checks_never_decisive():
    for c in CHECKSET_V1.checks:
        if c.is_record:
            snap = snapshot([person("顺顺")])
            st = stats(hygiene={"descriptive_resolved": 1, "descriptive_unresolved": 1},
                       merge={"merge_candidate_pairs": 1, "merged_pairs": 1,
                              "rejected_pairs": 0, "low_confidence_pairs": 0, "failed_pairs": 0})
            out = evaluate_check(c, snap, st)
            assert not out.is_decisive, f"[{c.id}] 记录型检查产生决定性结果"
