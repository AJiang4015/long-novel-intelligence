"""P20 report.py 渲染单测（纯字符串断言，无网络/Neo4j/LLM）。

覆盖（用户指定）：run / baseline / compare 三种报告，
以及 PASS / FAIL / OBSERVATION / INCONCLUSIVE / SKIP 各状态的渲染；
强制声明（TESTING.md §9）必须出现在标题下方。
"""

from __future__ import annotations

from tools.eval_framework.baseline import (
    BASELINE_INVALID,
    BASELINE_VALID,
    VERDICT_OK,
    VERDICT_REFUSE,
    aggregate_runs,
    compare_run,
)
from tools.eval_framework.checks import (
    OUTCOME_FAIL,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_OBSERVATION,
    OUTCOME_PASS,
    OUTCOME_SKIP,
)
from tools.eval_framework.report import (
    baseline_report,
    compare_report,
    run_report,
)


def _env() -> dict:
    return {"git_commit": "a1b2c3d4", "git_dirty": False, "model": "m1",
            "chunk_size": 4000, "chunk_overlap": 400, "concurrency": 4,
            "neo4j_version": "5.26", "novel_id": "n-1",
            "checkpoint_enabled": False, "llm_http_timeout": 300}


def _result(checks: list[dict]) -> dict:
    return {
        "schema_version": 1, "run_id": "run-1", "timestamp": "2026-08-28T00:00:00+00:00",
        "env": _env(), "corpus": {"name": "边城", "content_hash": "c1"},
        "compare_identity": {"corpus_hash": "c1", "checkset_version": "1", "model": "m1",
                             "chunk_size": 4000, "chunk_overlap": 400,
                             "chunker_version": "1", "extractor_version": "1",
                             "prompt_hashes": {"extraction": "e", "judge": "j", "merge": "m"}},
        "novel_id": "n-1", "job": {"job_id": "j-1", "status": "completed", "failed_blocks": []},
        "stats": {"job_status": "completed", "failed_blocks": [],
                  "counts": {"persons": 50, "relationships": 56},
                  "hygiene": {}, "merge": {}},
        "graph_snapshot": {"persons": [], "relationships": []},
        "checks": checks,
        "evidence_dump": {"persons": [{"canonical": "顺顺", "aliases": ["爹爹"],
                                       "alias_contexts": [{"alias": "爹爹", "chunk_id": 14,
                                                           "chapter_id": 13,
                                                           "snippet": "应当由大老爹爹作主"}]}]},
        "warnings": [],
    }


def _check(cid: str, outcome: str, **kw) -> dict:
    return {"check_id": cid, "outcome": outcome, "reason": kw.get("reason", ""),
            "actual": kw.get("actual"), "group": kw.get("group", "g"),
            "attribution": kw.get("attribution", "P08 / D-4"), "layer": kw.get("layer", "merge")}


# ---------------------------------------------------------------------------
# run 报告
# ---------------------------------------------------------------------------


def test_run_report_contains_declaration_and_env():
    md = run_report(_result([_check("A1", OUTCOME_PASS), _check("C1", OUTCOME_PASS)]))
    assert "不是下一轮修复方案" in md
    assert "验证记录" in md
    assert "| Git commit | a1b2c3d4 |" in md
    assert "| Model | m1 |" in md
    assert "| Novel ID | n-1 |" in md
    assert "| checkpoint_enabled | False |" in md


def test_run_report_renders_all_outcome_states():
    checks = [
        _check("A1", OUTCOME_PASS),
        _check("C1", OUTCOME_FAIL, reason="父亲 成为独立 Person", attribution="D-5 / D-6", layer="admission"),
        _check("C5", OUTCOME_OBSERVATION, actual={"person": True}),
        _check("A6", OUTCOME_INCONCLUSIVE, reason="G4 降级"),
        _check("A2", OUTCOME_SKIP, reason="无任何成员被提取（空洞防）"),
    ]
    md = run_report(_result(checks))
    assert "检查分布: PASS=1 / FAIL=1 / OBSERVATION=1 / INCONCLUSIVE=1 / SKIP=1" in md
    assert "| C1 | g | FAIL | D-5 / D-6 | admission | 父亲 成为独立 Person |" in md
    assert "C1** FAIL → attribution=D-5 / D-6" in md  # FAIL 归因路由节
    assert "C5: actual={'person': True}" in md        # OBSERVATION 记录值节
    assert "G4 降级" in md
    assert "Alias 证据" in md
    assert "爹爹" in md


def test_run_report_summary_line():
    md = run_report(_result([_check("A1", OUTCOME_PASS)]))
    assert "job status: `completed`" in md
    assert "persons=50 / relationships=56" in md


# ---------------------------------------------------------------------------
# baseline 报告
# ---------------------------------------------------------------------------


def _baseline_runs(outcomes: dict[str, list[str]]) -> list[dict]:
    runs_list = []
    for i in range(3):
        runs_list.append({
            "run_id": f"r{i}", "timestamp": "2026-08-28T00:00:00+00:00",
            "checks": [{"check_id": cid, "outcome": outs[i], "reason": "", "actual": None}
                       for cid, outs in outcomes.items()],
            "env": {"git_commit": "a1b2c3d4", "git_dirty": False, "model": "m1",
                    "concurrency": 4, "neo4j_version": "5.26"},
            "compare_identity": {"corpus_hash": "c1", "checkset_version": "1", "model": "m1",
                                 "chunk_size": 4000, "chunk_overlap": 400,
                                 "chunker_version": "1", "extractor_version": "1",
                                 "prompt_hashes": {"extraction": "e", "judge": "j", "merge": "m"}},
            "corpus": {"name": "边城"},
        })
    return runs_list


def test_baseline_report_valid():
    base = aggregate_runs(_baseline_runs({"A1": [OUTCOME_PASS] * 3,
                                          "C4": [OUTCOME_PASS, OUTCOME_PASS, OUTCOME_FAIL]}))
    md = baseline_report(base)
    assert "不是下一轮修复方案" in md
    assert "baseline_status: `VALID`" in md
    assert "| A1 |" in md and "stable" in md and "True" in md
    assert "variance" in md                      # C4 经验 variance
    assert "初判(先验)" in md                     # 先验列存在（仅展示）
    assert "stable failures" in md
    assert "（无）" in md                          # 无 stable failure


def test_baseline_report_invalid_lists_stable_failures():
    base = aggregate_runs(_baseline_runs({"C1": [OUTCOME_FAIL] * 3}))
    assert base["baseline_status"] == BASELINE_INVALID
    md = baseline_report(base)
    assert "baseline_status: `INVALID_NOT_REGRESSION_SAFE`" in md
    assert "禁止正常 REGRESSION 判定" in md
    assert "**C1**: {'FAIL': 3}" in md


def test_baseline_report_prior_column_shows_prior():
    base = aggregate_runs(_baseline_runs({"A1": [OUTCOME_PASS] * 3}))
    md = baseline_report(base)
    # A1 初判 variance 但经验 stable：两列并存，展示先验与经验的偏离
    assert "| A1 |" in md and "variance" in md and "stable" in md


# ---------------------------------------------------------------------------
# compare 报告
# ---------------------------------------------------------------------------


def test_compare_report_ok():
    base = aggregate_runs(_baseline_runs({"A1": [OUTCOME_PASS] * 3}))
    run = {"run_id": "new-run", "checks": [_check("A1", OUTCOME_FAIL)],
           "env": {"git_commit": "b" * 8, "git_dirty": False},
           "compare_identity": base["compare_identity"]}
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_OK
    md = compare_report(cmp)
    assert "verdict: `COMPARE_OK`" in md
    assert "不是下一轮修复方案" in md
    # provenance：不同 commit 仍比较（git_commit 仅记录）
    assert "| git_commit | a1b2c3d4 | bbbbbbbb |" in md
    assert "REGRESSION" in md


def test_compare_report_refuse_identity():
    base = aggregate_runs(_baseline_runs({"A1": [OUTCOME_PASS] * 3}))
    run = {"run_id": "new-run", "checks": [_check("A1", OUTCOME_PASS)],
           "env": {"git_commit": "b" * 8, "git_dirty": False},
           "compare_identity": {**base["compare_identity"], "model": "m2"}}
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_REFUSE
    md = compare_report(cmp)
    assert "verdict: `REFUSE_COMPARE`" in md
    assert "compare_identity 不匹配" in md
    assert "model" in md


def test_compare_report_refuse_invalid_baseline():
    base = aggregate_runs(_baseline_runs({"C1": [OUTCOME_FAIL] * 3}))
    run = {"run_id": "new-run", "checks": [_check("C1", OUTCOME_FAIL)],
           "env": {"git_commit": "b" * 8, "git_dirty": False},
           "compare_identity": base["compare_identity"]}
    cmp = compare_run(run, base)
    assert cmp["verdict"] == VERDICT_REFUSE
    md = compare_report(cmp)
    assert "INVALID_NOT_REGRESSION_SAFE" in md
    assert "禁止正常 REGRESSION 判定" in md
