"""P20 baseline.py 纯函数单测（全 mock 数据，无网络/Neo4j/LLM，TESTING.md §2）。

覆盖（用户指定 + Spec §4.3/§5.2/§7.1/§7.3 + §12 测试矩阵）：
- PASS/PASS/PASS → stable + satisfies_expected=true
- FAIL/FAIL/FAIL → stable failure + baseline INVALID
- PASS/PASS/FAIL → variance
- INCONCLUSIVE/SKIP 不参与 stable 分类（只入分布）
- **初判 outcome_class 不参与基线分类**（先验仅展示；真实数据偏离时诚实暴露）
- INVALID baseline → REFUSE_COMPARE
- git_commit 不同仍允许 compare（仅 provenance）
- compare_identity 不同才 REFUSE_COMPARE
- stable + run FAIL → REGRESSION；variance → OBSERVATION / drift
"""

from __future__ import annotations

import pytest

from tools.eval_framework.baseline import (
    BASELINE_INVALID,
    BASELINE_VALID,
    CLASS_STABLE,
    CLASS_UNCLASSIFIED,
    CLASS_VARIANCE,
    VERDICT_OK,
    VERDICT_REFUSE,
    aggregate_runs,
    classify_check_outcomes,
    compare_run,
)
from tools.eval_framework.checks import (
    OUTCOME_FAIL,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_PASS,
    OUTCOME_SKIP,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _identity(model: str = "m1", corpus_hash: str = "c1", chunk_size: int = 4000) -> dict:
    return {"corpus_hash": corpus_hash, "checkset_version": "1", "model": model,
            "chunk_size": chunk_size, "chunk_overlap": 400, "chunker_version": "1",
            "extractor_version": "1",
            "prompt_hashes": {"extraction": "e", "judge": "j", "merge": "m"}}


def make_run(run_id: str, check_outcomes: dict[str, str], *, git_commit: str = "a" * 8,
             model: str = "m1", corpus_hash: str = "c1") -> dict:
    return {
        "run_id": run_id,
        "checks": [{"check_id": k, "outcome": v, "reason": "", "actual": None}
                   for k, v in check_outcomes.items()],
        "env": {"git_commit": git_commit, "git_dirty": False, "model": model,
                "concurrency": 4, "neo4j_version": "5.26"},
        "compare_identity": _identity(model=model, corpus_hash=corpus_hash),
        "corpus": {"name": "边城"},
    }


def runs(*items) -> list[dict]:
    return [make_run(rid, outs) for rid, outs in items]


# ---------------------------------------------------------------------------
# 经验分类（Spec §4.3）
# ---------------------------------------------------------------------------


def test_pss_pass_pass_pass_stable_expected_true():
    cls = classify_check_outcomes([OUTCOME_PASS, OUTCOME_PASS, OUTCOME_PASS])
    assert cls["classification"] == CLASS_STABLE
    assert cls["satisfies_expected"] is True
    assert cls["outcome_distribution"] == {OUTCOME_PASS: 3}


def test_all_fail_is_stable_failure_not_variance():
    cls = classify_check_outcomes([OUTCOME_FAIL, OUTCOME_FAIL, OUTCOME_FAIL])
    assert cls["classification"] == CLASS_STABLE
    assert cls["satisfies_expected"] is False  # stable failure（v1.1 阻断项 1）


def test_pass_pass_fail_is_variance():
    cls = classify_check_outcomes([OUTCOME_PASS, OUTCOME_PASS, OUTCOME_FAIL])
    assert cls["classification"] == CLASS_VARIANCE
    assert cls["satisfies_expected"] is None


def test_inconclusive_skip_not_participating():
    # PASS/PASS/INCONCLUSIVE → 决定性 2 个 PASS → stable
    assert classify_check_outcomes([OUTCOME_PASS, OUTCOME_PASS, OUTCOME_INCONCLUSIVE])["classification"] == CLASS_STABLE
    # PASS/INCONCLUSIVE/SKIP → 决定性 1 个 → UNCLASSIFIED（保守）
    cls = classify_check_outcomes([OUTCOME_PASS, OUTCOME_INCONCLUSIVE, OUTCOME_SKIP])
    assert cls["classification"] == CLASS_UNCLASSIFIED
    # 全 INCONCLUSIVE → UNCLASSIFIED
    assert classify_check_outcomes([OUTCOME_INCONCLUSIVE] * 3)["classification"] == CLASS_UNCLASSIFIED
    # 分布仍记录全部结果
    assert classify_check_outcomes([OUTCOME_PASS, OUTCOME_PASS, OUTCOME_INCONCLUSIVE])["outcome_distribution"] == {
        OUTCOME_PASS: 2, OUTCOME_INCONCLUSIVE: 1}


# ---------------------------------------------------------------------------
# 聚合 → baseline（Spec §5.2 / §7.3）
# ---------------------------------------------------------------------------


def test_aggregate_pass_pass_pass_stable_and_valid():
    base = aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_PASS})))
    assert base["per_check"]["A1"]["classification"] == CLASS_STABLE
    assert base["per_check"]["A1"]["satisfies_expected"] is True
    assert base["baseline_status"] == BASELINE_VALID
    assert base["stable_failures"] == []


def test_aggregate_all_fail_invalid_with_stable_failures():
    base = aggregate_runs(runs(("r1", {"C1": OUTCOME_FAIL}), ("r2", {"C1": OUTCOME_FAIL}),
                               ("r3", {"C1": OUTCOME_FAIL})))
    assert base["per_check"]["C1"]["classification"] == CLASS_STABLE
    assert base["per_check"]["C1"]["satisfies_expected"] is False
    assert base["baseline_status"] == BASELINE_INVALID
    assert [sf["check_id"] for sf in base["stable_failures"]] == ["C1"]


def test_aggregate_variance_does_not_invalidate():
    base = aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_FAIL})))
    assert base["per_check"]["A1"]["classification"] == CLASS_VARIANCE
    assert base["baseline_status"] == BASELINE_VALID


def test_aggregate_mixed_checks():
    base = aggregate_runs(runs(
        ("r1", {"A1": OUTCOME_PASS, "C1": OUTCOME_PASS}),
        ("r2", {"A1": OUTCOME_PASS, "C1": OUTCOME_FAIL}),
        ("r3", {"A1": OUTCOME_FAIL, "C1": OUTCOME_PASS}),
    ))
    assert base["per_check"]["A1"]["classification"] == CLASS_VARIANCE
    assert base["per_check"]["C1"]["classification"] == CLASS_VARIANCE
    assert base["baseline_status"] == BASELINE_VALID


def test_prior_outcome_class_does_not_classify():
    """核心纪律：checkset 初判（A1=variance 先验 / C1=stable 先验）不参与基线分类。"""
    # A1 初判 variance，但 3 次全 PASS → 经验 stable（先验不遮住实际）
    base = aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_PASS})))
    assert base["per_check"]["A1"]["classification"] == CLASS_STABLE
    assert base["per_check"]["A1"]["prior_outcome_class"] == "variance"  # 仅展示
    # C1 初判 stable，但 PASS/PASS/FAIL → 经验 variance（诚实暴露偏离）
    base2 = aggregate_runs(runs(("r1", {"C1": OUTCOME_PASS}), ("r2", {"C1": OUTCOME_PASS}),
                                ("r3", {"C1": OUTCOME_FAIL})))
    assert base2["per_check"]["C1"]["classification"] == CLASS_VARIANCE
    assert base2["per_check"]["C1"]["prior_outcome_class"] == "stable"


def test_aggregate_attribution_layer_from_checkset():
    base = aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_PASS})))
    assert base["per_check"]["A1"]["attribution"] == "P08 / D-4"
    assert base["per_check"]["A1"]["layer"] == "merge"


def test_aggregate_heterogeneous_identity_raises():
    r1 = make_run("r1", {"A1": OUTCOME_PASS}, model="m1")
    r2 = make_run("r2", {"A1": OUTCOME_PASS}, model="m2")
    with pytest.raises(ValueError):
        aggregate_runs([r1, r2])


def test_aggregate_single_fail_with_skips_is_unclassified_with_note():
    base = aggregate_runs(runs(("r1", {"C1": OUTCOME_FAIL}), ("r2", {"C1": OUTCOME_SKIP}),
                               ("r3", {"C1": OUTCOME_SKIP})))
    assert base["per_check"]["C1"]["classification"] == CLASS_UNCLASSIFIED
    assert base["baseline_status"] == BASELINE_VALID  # 未宣称 stable failure → 不使基线 INVALID
    assert any("疑似稳定失败" in n for n in base["quality"]["notes"])


# ---------------------------------------------------------------------------
# compare（Spec §7.1）
# ---------------------------------------------------------------------------


def _valid_baseline() -> dict:
    return aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_PASS})))


def test_invalid_baseline_refuse_compare():
    base = aggregate_runs(runs(("r1", {"C1": OUTCOME_FAIL}), ("r2", {"C1": OUTCOME_FAIL}),
                               ("r3", {"C1": OUTCOME_FAIL})))
    run = make_run("new-run", {"C1": OUTCOME_FAIL})
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_REFUSE
    assert "INVALID" in cmp["reason"]
    assert cmp["stable_failures"][0]["check_id"] == "C1"


def test_git_commit_diff_allowed_compare():
    base = _valid_baseline()
    run = make_run("new-run", {"A1": OUTCOME_PASS}, git_commit="b" * 8)  # 不同 commit
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_OK
    assert cmp["provenance"]["baseline_git_commit"] == "a" * 8
    assert cmp["provenance"]["current_git_commit"] == "b" * 8


def test_identity_diff_refuse_compare():
    base = _valid_baseline()
    run = make_run("new-run", {"A1": OUTCOME_PASS}, model="m2")  # compare_identity 不同
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_REFUSE
    assert "model" in cmp["identity_diff"]
    assert "compare_identity 不匹配" in cmp["reason"]


def test_stable_fail_is_regression():
    base = _valid_baseline()  # A1 stable PASS
    run = make_run("new-run", {"A1": OUTCOME_FAIL})
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_OK
    assert cmp["regressions"] == ["A1"]
    verdicts = {pc["check_id"]: pc["verdict"] for pc in cmp["per_check"]}
    assert verdicts["A1"] == "REGRESSION"


def test_stable_pass_ok():
    base = _valid_baseline()
    cmp = compare_run(make_run("new-run", {"A1": OUTCOME_PASS}), base)
    assert cmp["verdict"] == VERDICT_OK
    assert cmp["regression_count"] == 0
    assert {pc["check_id"]: pc["verdict"] for pc in cmp["per_check"]}["A1"] == "PASS"


def test_variance_fail_is_observation_with_drift():
    base = aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_FAIL})))  # variance，多数 PASS
    cmp = compare_run(make_run("new-run", {"A1": OUTCOME_FAIL}), base)
    verdicts = {pc["check_id"]: pc for pc in cmp["per_check"]}
    assert verdicts["A1"]["verdict"] == "OBSERVATION"
    assert "与基线多数趋势相反" in verdicts["A1"]["note"]
    assert cmp["drift_notes"] == ["A1"]


def test_variance_pass_no_drift():
    base = aggregate_runs(runs(("r1", {"A1": OUTCOME_PASS}), ("r2", {"A1": OUTCOME_PASS}),
                               ("r3", {"A1": OUTCOME_FAIL})))
    cmp = compare_run(make_run("new-run", {"A1": OUTCOME_PASS}), base)
    assert {pc["check_id"]: pc["verdict"] for pc in cmp["per_check"]}["A1"] == "OBSERVATION"
    assert cmp["drift_notes"] == []


def test_skip_on_stable_not_counted():
    base = _valid_baseline()
    cmp = compare_run(make_run("new-run", {"A1": OUTCOME_SKIP}), base)
    assert {pc["check_id"]: pc["verdict"] for pc in cmp["per_check"]}["A1"] == "SKIP（不计）"
    assert cmp["regression_count"] == 0


def test_compare_attribution_layer_attached():
    base = _valid_baseline()
    cmp = compare_run(make_run("new-run", {"A1": OUTCOME_FAIL}), base)
    pc = {x["check_id"]: x for x in cmp["per_check"]}["A1"]
    assert pc["attribution"] == "P08 / D-4"
    assert pc["layer"] == "merge"
