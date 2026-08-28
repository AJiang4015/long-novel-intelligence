"""P20 baseline —— N 运行聚合、stable/variance 经验分类、satisfies_expected、baseline_status、compare
（Spec §5.2 / §7 / §7.3；Step 3）。

核心纪律（用户拍板，Step 3）：
- **checkset 的 outcome_class 只是先验，不参与基线分类**；分类完全由 N 次运行的实际
  决定性结果（PASS / FAIL）决定：

      checkset expectation → run outcomes → stable / variance → satisfies_expected → baseline_status

  这样真实运行数据与当前预期发生偏离时，系统**诚实暴露偏离**，而不是被初判标签「遮住」；
  checkset 初判仅作为报告展示字段（per_check.prior_outcome_class），明确标注为先验；
- **INCONCLUSIVE / SKIP 不参与 stable 分类**（只记录 outcome_distribution；决定性结果 < 2 次
  → UNCLASSIFIED，保守不宣称 stable）；
- stable/variance **描述结果稳定性，不描述 correctness**（Spec §4.3）；
- **baseline_status**：无 stable failure → `VALID`；存在（如 stable 检查 FAIL/FAIL/FAIL）→
  `INVALID_NOT_REGRESSION_SAFE`——事实照存，但**禁止用于正常 REGRESSION 判定**（§7.3）；
- **compare**：git_commit / git_dirty 仅 provenance（不同 commit 仍允许 compare——回归比较的
  正常场景）；compare 兼容性唯一依据 = **compare_identity**，不匹配才 REFUSE_COMPARE；
  INVALID 基线 → REFUSE_COMPARE（§7.1）。

本模块为**纯函数层**（零 I/O、零 LLM、零 Neo4j）：输入 runner 产出的 run result dict /
baseline dict，输出聚合与判定结果；文件读写与 CLI 接线由后续集成步骤负责（不在本步）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from tools.eval_framework.checks import (
    CHECKSET_V2,
    DECISIVE_OUTCOMES,
    OUTCOME_FAIL,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_PASS,
    OUTCOME_SKIP,
)

# 经验分类（Spec §4.3）
CLASS_STABLE = "stable"
CLASS_VARIANCE = "variance"
CLASS_UNCLASSIFIED = "unclassified"

# baseline 有效性（Spec §7.3）
BASELINE_VALID = "VALID"
BASELINE_INVALID = "INVALID_NOT_REGRESSION_SAFE"

# compare 判定（Spec §7.1）
VERDICT_OK = "COMPARE_OK"
VERDICT_REFUSE = "REFUSE_COMPARE"

#: 决定性结果最少样本数（<2 次无法宣称 stable，保守 UNCLASSIFIED）
_MIN_DECISIVE_FOR_STABLE = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. stable / variance 经验分类（Spec §4.3）
# ---------------------------------------------------------------------------


def classify_check_outcomes(outcomes: Sequence[str]) -> dict[str, Any]:
    """纯函数：N 次运行该检查的 outcome 列表 → 经验分类 + satisfies_expected + 分布。

    - 只基于决定性结果（PASS / FAIL）；INCONCLUSIVE / SKIP 只入分布、不参与分类；
    - **不使用 checkset.outcome_class 初判**（初判仅是报告展示字段）；
    - 返回：{classification, satisfies_expected, outcome_distribution, decisive_count}。
    """
    dist: dict[str, int] = {}
    for o in outcomes:
        dist[o] = dist.get(o, 0) + 1
    decisive = [o for o in outcomes if o in DECISIVE_OUTCOMES]
    if len(decisive) < _MIN_DECISIVE_FOR_STABLE:
        return {"classification": CLASS_UNCLASSIFIED, "satisfies_expected": None,
                "outcome_distribution": dist, "decisive_count": len(decisive)}
    if len(set(decisive)) == 1:
        all_pass = decisive[0] == OUTCOME_PASS
        return {"classification": CLASS_STABLE, "satisfies_expected": all_pass,
                "outcome_distribution": dist, "decisive_count": len(decisive)}
    return {"classification": CLASS_VARIANCE, "satisfies_expected": None,
            "outcome_distribution": dist, "decisive_count": len(decisive)}


# ---------------------------------------------------------------------------
# 2. N 运行聚合 → baseline artifact（Spec §5.2 / §6.2 / §7.3）
# ---------------------------------------------------------------------------


def _run_checks_map(run: dict) -> dict[str, str]:
    """run result 的 checks → {check_id: outcome}。"""
    return {o["check_id"]: o["outcome"] for o in run.get("checks", [])}


def aggregate_runs(runs: Sequence[dict], *, checkset=None, baseline_id: str | None = None) -> dict:
    """N 个 run result → baseline artifact（Spec §5.2 schema）。

    - 校验：所有 run 的 compare_identity 必须一致（异构 run 不可聚合为同一基线）；
    - per_check：经验分类 + satisfies_expected + outcome_distribution +
      checkset 元数据（attribution / layer / group / description / **prior_outcome_class 先验，仅展示**）；
    - baseline_status：存在 stable failure → INVALID_NOT_REGRESSION_SAFE，否则 VALID。
    """
    if not runs:
        raise ValueError("aggregate_runs 至少需要 1 个 run")
    cs = checkset if checkset is not None else CHECKSET_V2

    first_ci = dict(runs[0].get("compare_identity") or {})
    for r in runs[1:]:
        if dict(r.get("compare_identity") or {}) != first_ci:
            raise ValueError("runs 的 compare_identity 不一致（不同语料/配置/版本不可聚合为同一基线）")

    check_ids = sorted({cid for r in runs for cid in _run_checks_map(r)})
    per_check: dict[str, dict[str, Any]] = {}
    for cid in check_ids:
        outcomes = [o for r in runs for o in [_run_checks_map(r).get(cid)] if o is not None]
        entry = classify_check_outcomes(outcomes)
        meta = cs.by_id(cid)
        if meta is not None:
            entry.update({
                "prior_outcome_class": meta.outcome_class,   # 仅展示：初判先验，不参与分类
                "attribution": meta.attribution,
                "layer": meta.layer,
                "group": meta.group,
                "description": meta.description,
            })
        per_check[cid] = entry

    stable_failures = [
        {"check_id": cid, "outcome_distribution": pc["outcome_distribution"]}
        for cid, pc in per_check.items()
        if pc["classification"] == CLASS_STABLE and pc["satisfies_expected"] is False
    ]
    status = BASELINE_VALID if not stable_failures else BASELINE_INVALID

    notes: list[str] = []
    for cid, pc in per_check.items():
        if pc["classification"] == CLASS_UNCLASSIFIED and pc["decisive_count"] == 1 \
                and pc["outcome_distribution"].get(OUTCOME_FAIL, 0) == 1:
            notes.append(f"[{cid}] 仅有 1 次决定性 FAIL（其余 SKIP/INCONCLUSIVE）——疑似稳定失败但样本不足，未判 stable")

    first_env = runs[0].get("env") or {}
    return {
        "schema_version": 1,
        "baseline_id": baseline_id or f"biancheng-{first_ci.get('checkset_version', 'v1')}-{_now_iso()[:10]}",
        "created": _now_iso(),
        "runs": [r.get("run_id", "?") for r in runs],
        "provenance": {  # git_commit/git_dirty 仅 provenance，不参与 compare 兼容性（Spec §7.1）
            "git_commit": first_env.get("git_commit"),
            "git_dirty": first_env.get("git_dirty"),
            "model": first_env.get("model"),
            "concurrency": first_env.get("concurrency"),
            "neo4j_version": first_env.get("neo4j_version"),
        },
        "compare_identity": first_ci,
        "checkset_version": first_ci.get("checkset_version"),
        "corpus": runs[0].get("corpus"),
        "baseline_status": status,
        "stable_failures": stable_failures,
        "per_check": per_check,
        "quality": {
            "run_count": len(runs),
            "stable_check_count": sum(1 for pc in per_check.values()
                                      if pc["classification"] == CLASS_STABLE),
            "stable_failure_count": len(stable_failures),
            "variance_check_count": sum(1 for pc in per_check.values()
                                        if pc["classification"] == CLASS_VARIANCE),
            "unclassified_check_count": sum(1 for pc in per_check.values()
                                            if pc["classification"] == CLASS_UNCLASSIFIED),
            "notes": notes,
        },
    }


# ---------------------------------------------------------------------------
# 3. compare（Spec §7.1）
# ---------------------------------------------------------------------------


def _identity_diff(ci_a: dict, ci_b: dict) -> list[str]:
    keys = sorted(set(ci_a) | set(ci_b))
    return [k for k in keys if ci_a.get(k) != ci_b.get(k)]


def _majority_outcome(distribution: dict) -> str | None:
    """variance 检查的基线多数趋势（PASS≥FAIL 视为 PASS；无决定性结果 → None）。"""
    passes = distribution.get(OUTCOME_PASS, 0)
    fails = distribution.get(OUTCOME_FAIL, 0)
    if passes == 0 and fails == 0:
        return None
    return OUTCOME_PASS if passes >= fails else OUTCOME_FAIL


def _check_verdict(check_id: str, outcome: str, bpc: dict) -> tuple[str, str]:
    """单检查 compare 判定（Spec §7.1 判定表）。返回 (verdict, note)。"""
    cls = bpc.get("classification")
    if outcome in (OUTCOME_SKIP, OUTCOME_INCONCLUSIVE):
        return f"{outcome}（不计）", "决定性结果缺失，不参与回归判定"
    if cls == CLASS_STABLE:
        if bpc.get("satisfies_expected") is False:
            return "INVALID_BASELINE", "基线该检查为 stable failure（基线应已被 REFUSE_COMPARE 拦截）"
        if outcome == OUTCOME_PASS:
            return "PASS", "stable 检查满足 expected"
        return "REGRESSION", "stable 检查 FAIL（基线 VALID）→ REGRESSION，按 attribution/layer 归因"
    # variance / unclassified → OBSERVATION（Spec §7.1：variance → OBSERVATION / drift）
    note = f"variance/unclassified 检查，本次 outcome={outcome}"
    majority = _majority_outcome(bpc.get("outcome_distribution") or {})
    if majority in (OUTCOME_PASS, OUTCOME_FAIL) and outcome != majority:
        d = bpc.get("outcome_distribution") or {}
        note += (f"；与基线多数趋势相反（基线 N={sum(d.values())} "
                 f"PASS={d.get(OUTCOME_PASS, 0)} FAIL={d.get(OUTCOME_FAIL, 0)}），"
                 f"建议趋势复跑（不自动判回归）")
    return "OBSERVATION", note


def compare_run(run: dict, baseline: dict) -> dict:
    """单次运行 vs 基线（Spec §7.1）。

    REFUSE_COMPARE 情形：
    1. 基线 baseline_status == INVALID_NOT_REGRESSION_SAFE（§7.3：禁止正常 REGRESSION 判定）；
    2. compare_identity 不匹配（corpus_hash / checkset_version / model / chunk_size /
       chunk_overlap / chunker_version / extractor_version / prompt_hashes 任一不同）。
    **git_commit / git_dirty 差异不拒绝**——仅记录 provenance（回归比较的正常场景）。
    """
    run_id = run.get("run_id", "?")
    baseline_id = baseline.get("baseline_id", "?")

    if baseline.get("baseline_status") == BASELINE_INVALID:
        return {
            "verdict": VERDICT_REFUSE,
            "reason": "INVALID_NOT_REGRESSION_SAFE：基线存在 stable failure，禁止正常 REGRESSION 判定（Spec §7.3）",
            "baseline_id": baseline_id, "run_id": run_id,
            "stable_failures": baseline.get("stable_failures", []),
        }

    diff = _identity_diff(dict(run.get("compare_identity") or {}),
                          dict(baseline.get("compare_identity") or {}))
    if diff:
        return {
            "verdict": VERDICT_REFUSE,
            "reason": f"compare_identity 不匹配（{', '.join(diff)}）→ REFUSE_COMPARE（Spec §7.1）；git_commit 差异不拒绝",
            "baseline_id": baseline_id, "run_id": run_id,
            "identity_diff": diff,
        }

    per_check = []
    regressions: list[str] = []
    drift_notes: list[str] = []
    for o in run.get("checks", []):
        cid = o["check_id"]
        bpc = baseline.get("per_check", {}).get(cid, {})
        verdict, note = _check_verdict(cid, o["outcome"], bpc)
        per_check.append({
            "check_id": cid,
            "outcome": o["outcome"],
            "baseline_classification": bpc.get("classification"),
            "baseline_satisfies_expected": bpc.get("satisfies_expected"),
            "baseline_distribution": bpc.get("outcome_distribution"),
            "verdict": verdict,
            "note": note,
            "attribution": bpc.get("attribution"),
            "layer": bpc.get("layer"),
        })
        if verdict == "REGRESSION":
            regressions.append(cid)
        if "与基线多数趋势相反" in note:
            drift_notes.append(cid)

    run_env = run.get("env") or {}
    base_env = baseline.get("provenance") or {}
    return {
        "verdict": VERDICT_OK,
        "baseline_id": baseline_id,
        "run_id": run_id,
        "provenance": {  # git_commit/git_dirty 仅记录（不同 commit 允许 compare，Spec §7.1）
            "baseline_git_commit": base_env.get("git_commit"),
            "current_git_commit": run_env.get("git_commit"),
            "baseline_git_dirty": base_env.get("git_dirty"),
            "current_git_dirty": run_env.get("git_dirty"),
        },
        "per_check": per_check,
        "regressions": regressions,
        "regression_count": len(regressions),
        "drift_notes": drift_notes,
    }
