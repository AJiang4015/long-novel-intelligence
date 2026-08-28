"""P20 report —— TESTING.md §9 模板 markdown 生成（Spec §9/§13；Step 3）。

- **强制声明（TESTING.md §9）**：报告是当前版本的验证记录，不是下一轮修复方案；
  任何后续代码修改需另立设计 / Problem Record；
- 支持三种报告：run（单次运行）/ baseline（基线）/ compare（回归比较）；
- **纯函数**：输入 result / baseline / compare dict → markdown 字符串（零 I/O）；
  落盘由集成步骤负责（不在本步）。
"""

from __future__ import annotations

from typing import Any

from tools.eval_framework.baseline import (
    BASELINE_INVALID,
    CLASS_STABLE,
    CLASS_UNCLASSIFIED,
    CLASS_VARIANCE,
    VERDICT_OK,
)

_DECLARATION = ("**本报告是当前版本（git commit 见 Environment Baseline）的验证记录，"
                "不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**")

_OUTCOME_ORDER = ("PASS", "FAIL", "OBSERVATION", "INCONCLUSIVE", "SKIP")


def _summary_counts(checks: list[dict]) -> str:
    counts = {k: 0 for k in _OUTCOME_ORDER}
    for o in checks:
        counts[o["outcome"]] = counts.get(o["outcome"], 0) + 1
    return " / ".join(f"{k}={counts[k]}" for k in _OUTCOME_ORDER)


def _env_rows(env: dict) -> str:
    rows = [
        ("Git commit", env.get("git_commit")),
        ("Git dirty", env.get("git_dirty")),
        ("Neo4j", env.get("neo4j_version")),
        ("Model", env.get("model")),
        ("chunk_size / overlap / concurrency",
         f"{env.get('chunk_size')} / {env.get('chunk_overlap')} / {env.get('concurrency')}"),
        ("Novel ID", env.get("novel_id")),
        ("checkpoint_enabled", env.get("checkpoint_enabled")),
        ("llm_http_timeout", env.get("llm_http_timeout")),
    ]
    return "\n".join(f"| {k} | {v} |" for k, v in rows)


def _checks_table(checks: list[dict]) -> str:
    lines = ["| id | group | outcome | attribution | layer | 说明 |",
             "|---|---|---|---|---|---|"]
    for o in checks:
        desc = o.get("reason") or ""
        actual = o.get("actual")
        if actual is not None:
            desc = (desc + f" actual={actual}" if desc else f"actual={actual}")
        lines.append(f"| {o['check_id']} | {o.get('group', '')} | {o['outcome']} "
                     f"| {o.get('attribution', '')} | {o.get('layer', '')} | {desc} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# run 报告
# ---------------------------------------------------------------------------


def run_report(result: dict) -> str:
    env = result.get("env") or {}
    checks = result.get("checks") or []
    job = result.get("job") or {}
    stats = result.get("stats") or {}
    counts = stats.get("counts") or {}
    commit = (env.get("git_commit") or "unknown")[:8]
    title = f"# P20 Evaluation Report — 《{result.get('corpus', {}).get('name', '?')}》（{result.get('timestamp', '')[:10]}）"

    evidence = result.get("evidence_dump") or {}
    ev_lines = []
    for p in evidence.get("persons", [])[:10]:
        ev_lines.append(f"- **{p['canonical']}**（aliases={p['aliases']}）")
        for c in p.get("alias_contexts", [])[:3]:
            ev_lines.append(f"  - `{c['alias']}` chunk{c['chunk_id']}/ch{c['chapter_id']}: …{c['snippet']}…")

    fails = [o for o in checks if o["outcome"] == "FAIL"]
    fail_lines = []
    for o in fails:
        fail_lines.append(f"- **{o['check_id']}** FAIL → attribution={o.get('attribution')} / "
                          f"layer={o.get('layer')}（PIPELINE_LAYER §4 归因链）— {o.get('reason')}")

    obs_lines = []
    for o in checks:
        if o["outcome"] == "OBSERVATION" and o.get("actual") is not None:
            obs_lines.append(f"- {o['check_id']}: actual={o['actual']}")

    return "\n".join([
        title,
        "",
        f"> {_DECLARATION}",
        "",
        "## 1. Environment Baseline（TESTING.md §6）",
        "",
        "| 项 | 值 |",
        "|---|---|",
        _env_rows(env),
        "",
        "## 2. 结果摘要",
        "",
        f"- job status: `{job.get('status')}`；persons={counts.get('persons')} / relationships={counts.get('relationships')}",
        f"- 检查分布: {_summary_counts(checks)}",
        *(f"- warning: {w}" for w in result.get("warnings") or []),
        "",
        "## 3. 检查结果",
        "",
        _checks_table(checks),
        "",
        "## 4. Alias 证据（evidence dump 节选，供人工可解释性复核）",
        "",
        *ev_lines,
        "",
        "## 5. 失败与观察",
        "",
        "### FAIL（归因路由）",
        "",
        *(fail_lines or ["- （无）"]),
        "",
        "### OBSERVATION 记录值",
        "",
        *(obs_lines or ["- （无）"]),
        "",
        "### INCONCLUSIVE / SKIP",
        "",
        *(["- " + o["reason"] for o in checks
           if o["outcome"] in ("INCONCLUSIVE", "SKIP") and o.get("reason")] or ["- （无）"]),
        "",
        "## 6. Known Limitations / Notes",
        "",
        "- 单次运行不构成结论（P06 非确定性，TESTING.md §3）：趋势需多次运行（`--runs N`）或与基线比较。",
        "",
    ])


# ---------------------------------------------------------------------------
# baseline 报告
# ---------------------------------------------------------------------------


def _class_label(cls: str | None) -> str:
    return {CLASS_STABLE: "stable", CLASS_VARIANCE: "variance",
            CLASS_UNCLASSIFIED: "unclassified"}.get(cls, str(cls))


def baseline_report(baseline: dict) -> str:
    status = baseline.get("baseline_status")
    title = f"# P20 Baseline Report — 《{baseline.get('corpus', {}).get('name', '?')}》（{baseline.get('created', '')[:10]}）"

    table_lines = ["| id | group | 经验分类 | satisfies_expected | outcome_distribution | 初判(先验) | attribution | layer |",
                   "|---|---|---|---|---|---|---|---|"]
    for cid, pc in (baseline.get("per_check") or {}).items():
        table_lines.append(
            f"| {cid} | {pc.get('group', '')} | {_class_label(pc.get('classification'))} "
            f"| {pc.get('satisfies_expected')} | {pc.get('outcome_distribution')} "
            f"| {pc.get('prior_outcome_class', '')} | {pc.get('attribution', '')} | {pc.get('layer', '')} |")

    sf_lines = []
    for sf in baseline.get("stable_failures") or []:
        sf_lines.append(f"- **{sf['check_id']}**: {sf['outcome_distribution']}（stable failure，基线 INVALID）")

    notes = baseline.get("quality", {}).get("notes") or []
    ci = baseline.get("compare_identity") or {}
    return "\n".join([
        title,
        "",
        f"> {_DECLARATION}",
        "",
        "## 1. Baseline 元数据",
        "",
        f"- baseline_id: `{baseline.get('baseline_id')}`；runs={baseline.get('runs')}",
        f"- checkset_version: {baseline.get('checkset_version')}；run_count: {baseline.get('quality', {}).get('run_count')}",
        f"- **baseline_status: `{status}`**"
        + ("" if status != BASELINE_INVALID else "（存在 stable failure，禁止正常 REGRESSION 判定，Spec §7.3）"),
        f"- compare_identity: corpus_hash={str(ci.get('corpus_hash', ''))[:12]}… model={ci.get('model')} "
        f"chunk={ci.get('chunk_size')}/{ci.get('chunk_overlap')} chunker={ci.get('chunker_version')} "
        f"extractor={ci.get('extractor_version')}",
        f"- provenance（git_commit 仅记录，不参与 compare 兼容性）: {baseline.get('provenance')}",
        "",
        "## 2. per-check 分类（经验分类由 N 次运行决定性结果决定；初判仅展示先验）",
        "",
        "\n".join(table_lines),
        "",
        "## 3. stable failures（若存在）",
        "",
        *(sf_lines or ["- （无）"]),
        "",
        "## 4. variance / unclassified 分布",
        "",
        *([f"- {cid}: {pc['outcome_distribution']}（{_class_label(pc.get('classification'))}）"
           for cid, pc in (baseline.get("per_check") or {}).items()
           if pc.get("classification") in (CLASS_VARIANCE, CLASS_UNCLASSIFIED)] or ["- （无）"]),
        "",
        "## 5. quality 汇总",
        "",
        f"- stable_check_count={baseline.get('quality', {}).get('stable_check_count')} / "
        f"stable_failure_count={baseline.get('quality', {}).get('stable_failure_count')} / "
        f"variance_check_count={baseline.get('quality', {}).get('variance_check_count')} / "
        f"unclassified_check_count={baseline.get('quality', {}).get('unclassified_check_count')}",
        *(f"- note: {n}" for n in notes),
        "",
    ])


# ---------------------------------------------------------------------------
# compare 报告
# ---------------------------------------------------------------------------


def compare_report(cmp: dict) -> str:
    verdict = cmp.get("verdict")
    title = f"# P20 Compare Report — run vs baseline（{cmp.get('run_id', '')[:8]}）"

    if verdict != VERDICT_OK:
        return "\n".join([
            title,
            "",
            f"> {_DECLARATION}",
            "",
            "## 1. 判定",
            "",
            f"- **verdict: `{verdict}`**",
            f"- reason: {cmp.get('reason')}",
            *(f"- stable_failure: {sf}" for sf in cmp.get("stable_failures") or []),
            *(f"- identity_diff: {d}" for d in cmp.get("identity_diff") or []),
            "",
        ])

    table_lines = ["| id | outcome | baseline 分类 | verdict | attribution | layer | note |",
                   "|---|---|---|---|---|---|---|"]
    for pc in cmp.get("per_check") or []:
        table_lines.append(
            f"| {pc['check_id']} | {pc['outcome']} | {_class_label(pc.get('baseline_classification'))} "
            f"| {pc['verdict']} | {pc.get('attribution', '')} | {pc.get('layer', '')} | {pc.get('note', '')} |")

    prov = cmp.get("provenance") or {}
    reg_lines = [f"- **{cid}**（按 attribution/layer 归因，PIPELINE_LAYER §4）"
                 for cid in cmp.get("regressions") or []]
    drift_lines = [f"- {cid}" for cid in cmp.get("drift_notes") or []]
    return "\n".join([
        title,
        "",
        f"> {_DECLARATION}",
        "",
        "## 1. 判定",
        "",
        f"- **verdict: `{verdict}`**；baseline_id={cmp.get('baseline_id')}；run_id={cmp.get('run_id')}",
        "",
        "## 2. Provenance（git_commit 仅记录，不参与判定——回归比较的正常场景 = 不同 commit vs 历史基线）",
        "",
        "| 项 | 基线 | 当前 |",
        "|---|---|---|",
        f"| git_commit | {prov.get('baseline_git_commit')} | {prov.get('current_git_commit')} |",
        f"| git_dirty | {prov.get('baseline_git_dirty')} | {prov.get('current_git_dirty')} |",
        "",
        "## 3. per-check verdicts",
        "",
        "\n".join(table_lines),
        "",
        "## 4. 汇总",
        "",
        f"- REGRESSION: {cmp.get('regression_count')}",
        *(reg_lines or ["  - （无）"]),
        f"- drift 提示（variance 与基线多数趋势相反，建议趋势复跑）:",
        *(drift_lines or ["  - （无）"]),
        "",
    ])
