"""P20 checkset v1 —— 声明式检查集 + 纯函数判定（Spec §4/§5/§7.1）。

定位（Spec §10.1）：
- checkset = TESTING.md §4/§9.1 + P16/P17/P18 验收的**可执行编码**（v1.1 语义）；
- 本模块是**纯函数层**：零 I/O、零 LLM、零 Neo4j、零 app 依赖——只接受普通 dict
  输入（SNAPSHOT / STATS），输出 CheckOutcome 判定；
- 数据采集（Neo4j 查询 / API / sections 确定性分类 / 文件系统检查）由 runner.py 负责
  （Step 2），本模块只定义输入契约（见 SNAPSHOT / STATS）与判定规则；
- 判定分类（Spec §4.3/§5.2）：PASS / FAIL / OBSERVATION / INCONCLUSIVE / SKIP；
  **stable/variance 经验重分类与 baseline_status 归 baseline.py（Step 3）**，本模块只提供
  检查定义（outcome_class 初判）与单次判定。

不变量（Spec §4.2 语义边界：修改检查期望 = 修改决策，需独立立项/解除冻结）：
- 冻结语义（D-5/D-6/D-9/D-10/D-13/D-17，P16/P17/P18）已编码为 attribution / layer；
- OBSERVATION 类检查（C5/D2/E1/F1/B2/G2/G4）**记录不判败**（AGENTS.md §3 红线）；
- 修改本文件 checkset 定义（期望/分类/归因/新增检查）必须 bump `checkset_version`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 判定分类常量（Spec §4.3 / §5.2）
# ---------------------------------------------------------------------------

OUTCOME_PASS = "PASS"
OUTCOME_FAIL = "FAIL"
OUTCOME_OBSERVATION = "OBSERVATION"
OUTCOME_INCONCLUSIVE = "INCONCLUSIVE"
OUTCOME_SKIP = "SKIP"

#: 决定性结果（基线 stable/variance 经验分类与 satisfies_expected 只基于这两者，§4.3）
DECISIVE_OUTCOMES = (OUTCOME_PASS, OUTCOME_FAIL)

#: outcome_class 初判合法值：stable/variance = 可决定性检查；observation = 记录型检查
_CLASS_STABLE = "stable"
_CLASS_VARIANCE = "variance"
_CLASS_OBSERVATION = "observation"

# ---------------------------------------------------------------------------
# 输入契约（runner 采集，本模块只读）
# ---------------------------------------------------------------------------

# SNAPSHOT = {
#   "novel_id": str,
#   "persons": [ {"name", "aliases": [...], "mention_count", "chapters": [...], "chunk_ids": [...]} ],
#   "relationships": [ {"source", "target", "type", ...} ],
#   "labels_used": ["Novel", "Person", ...],        # G1（runner 查询本 novel 子图 labels）
#   "novel_ids_seen": [novel_id, ...],              # G3（runner 采样本 novel 相关节点 novel_id 集合）
#   "alias_search": { q: {"hits": [{"name", "aliases": [...]}]} },   # A6（runner 经 characters API 采集）
#   "counts": { "nonbody_canonical_count": int, ... },   # B1（runner 经 sections 确定性分类计算）
#   "checkpoint_dir_exists": bool,                  # G5（runner 文件系统检查）
# }
#
# STATS = {
#   "job_status": "completed | completed_with_errors | failed",
#   "failed_blocks": [ {"chunk_id": int, "chapter_id": int, "error": str} ],
#   "counts": {"persons": int, "relationships": int},
#   "hygiene": {"collective_filtered", "generic_filtered", "descriptive_resolved",
#               "composite_resolved", "invalid_filtered", "nonbody_person_provisional",
#               "nonbody_descriptive_dropped", "nonbody_provisional_dropped",
#               "descriptive_unresolved", "composite_unresolved"},
#   "merge": {"merge_candidate_pairs", "merged_pairs", "rejected_pairs",
#             "low_confidence_pairs", "failed_pairs"},
# }

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckDef:
    """一条检查定义。expectation.kind 决定判定函数（见 _EVALUATORS）。"""

    id: str
    group: str
    description: str
    expectation: dict[str, Any]
    #: AND 语义前置条件；形如 "person_exists:NAME"（空洞 PASS 防，Spec §4.1）
    preconditions: tuple[str, ...] = ()
    #: OR 语义前置条件：任一成立即通过前置
    precondition_any: tuple[str, ...] = ()
    #: G4：job 存在失败 chunk 时，需要全语料证据的检查降级 INCONCLUSIVE（Spec §4.2 G4）
    needs_full_corpus: bool = True
    #: 初判先验：stable / variance / observation（基线按决定性结果经验重分类，§4.3）
    outcome_class: str = _CLASS_VARIANCE
    #: 决策/问题归属（修改期望=修改决策；禁止以 FAIL 形式重开冻结语义）
    attribution: str = ""
    #: PIPELINE_LAYER §4 归因链层（extraction/recall/judge/admission/registration/merge/db/...）
    layer: str = ""
    severity: str = "normal"

    @property
    def is_record(self) -> bool:
        """记录型检查（永不产生决定性结果，G4 不降级、baseline 不判稳定）。"""
        return self.outcome_class == _CLASS_OBSERVATION


@dataclass(frozen=True)
class CheckOutcome:
    check_id: str
    outcome: str
    reason: str = ""
    actual: dict[str, Any] | None = None

    @property
    def is_decisive(self) -> bool:
        return self.outcome in DECISIVE_OUTCOMES


@dataclass(frozen=True)
class CheckSet:
    schema_version: int
    checkset_version: str
    applies_to: str
    corpus: dict[str, str]
    checks: tuple[CheckDef, ...]

    def by_id(self, check_id: str) -> CheckDef | None:
        for c in self.checks:
            if c.id == check_id:
                return c
        return None


# ---------------------------------------------------------------------------
# 判定辅助（纯函数）
# ---------------------------------------------------------------------------


def _person_named(snapshot: dict, name: str) -> list[dict]:
    """canonical name == name 的 persons。"""
    return [p for p in snapshot.get("persons", []) if p.get("name") == name]


def _persons_by_mention(snapshot: dict, name: str) -> list[dict]:
    """mention 语义：canonical 或任一 alias 命中 name 的 persons（D-4 别名语义）。"""
    return [p for p in snapshot.get("persons", [])
            if p.get("name") == name or name in (p.get("aliases") or [])]


def _eval_precondition(cond: str, snapshot: dict) -> bool:
    if cond.startswith("person_exists:"):
        return bool(_persons_by_mention(snapshot, cond[len("person_exists:"):]))
    raise ValueError(f"未知前置条件: {cond!r}")


def _preconditions_met(check: CheckDef, snapshot: dict) -> tuple[bool, str]:
    for cond in check.preconditions:
        if not _eval_precondition(cond, snapshot):
            return False, cond
    if check.precondition_any:
        if not any(_eval_precondition(c, snapshot) for c in check.precondition_any):
            return False, "any:" + ",".join(check.precondition_any)
    return True, ""


def _stats_get(stats: dict, dotted: str) -> Any:
    """按点路径取 stats 值："hygiene.descriptive_unresolved" / "merge.failed_pairs" / "failed_blocks"。"""
    cur: Any = stats
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _failed_chunk_ids(stats: dict) -> list[int]:
    return [b.get("chunk_id") for b in (stats.get("failed_blocks") or [])
            if isinstance(b, dict) and b.get("chunk_id") is not None]


# ---------------------------------------------------------------------------
# 检查判定函数（kind → evaluator）
# ---------------------------------------------------------------------------


def _eval_single_canonical_with_aliases(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """A1/A2：一组 mention 必须归并为同一 canonical，且其余名 ∈ aliases（TESTING.md §4 正向）。"""
    exp = check.expectation
    members = set(exp["members"])
    cands = [p for p in snapshot.get("persons", [])
             if ({p.get("name")} | set(p.get("aliases") or [])) & members]
    if not cands:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="无任何成员被提取（空洞防）")
    canonicals = sorted({p["name"] for p in cands})
    if len(canonicals) > 1:
        return CheckOutcome(check.id, OUTCOME_FAIL, reason="成员分裂为多个 canonical",
                            actual={"canonicals": canonicals})
    canon = cands[0]
    aliases = canon.get("aliases") or []
    missing = [m for m in exp.get("alias_contains", [])
               if m != canon["name"] and m not in aliases]
    if missing:
        return CheckOutcome(check.id, OUTCOME_FAIL, reason=f"aliases 缺失: {missing}",
                            actual={"canonical": canon["name"], "aliases": aliases})
    return CheckOutcome(check.id, OUTCOME_PASS,
                        actual={"canonical": canon["name"], "aliases": aliases})


def _eval_aliased_into(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """A3/A4：alias 必须被吸收进 target.aliases，且不成为独立 canonical。"""
    exp = check.expectation
    alias, target = exp["alias"], exp["target"]
    targets = _persons_by_mention(snapshot, target)
    if not targets:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason=f"目标 {target} 未被提取（空洞防）")
    if _person_named(snapshot, alias):
        return CheckOutcome(check.id, OUTCOME_FAIL, reason=f"{alias} 成为独立 canonical（碎片化）",
                            actual={"fragment_person": alias})
    t = targets[0]
    aliases = t.get("aliases") or []
    if alias in aliases:
        return CheckOutcome(check.id, OUTCOME_PASS,
                            actual={"target": t["name"], "alias": alias, "aliases": aliases})
    return CheckOutcome(check.id, OUTCOME_FAIL, reason=f"{alias} 未吸收进 {t['name']}.aliases",
                        actual={"target": t["name"], "aliases": aliases})


def _eval_distinct_persons(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """A5 负向：两个不同人物必须保持不同 canonical（TESTING.md §4 负向）。"""
    exp = check.expectation
    pa = _persons_by_mention(snapshot, exp["a"])
    pb = _persons_by_mention(snapshot, exp["b"])
    if not pa or not pb:
        return CheckOutcome(check.id, OUTCOME_SKIP,
                            reason=f"{exp['a']}/{exp['b']} 未全部被提取（空洞防）")
    if pa[0]["name"] == pb[0]["name"]:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"{exp['a']} 与 {exp['b']} 被误合并为 {pa[0]['name']}",
                            actual={"canonical": pa[0]["name"]})
    return CheckOutcome(check.id, OUTCOME_PASS,
                        actual={"a": pa[0]["name"], "b": pb[0]["name"]})


def _eval_alias_search_unique(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """A6：搜索 q 必须唯一命中 expected_name 的 canonical（TESTING.md §4 验证项）。"""
    exp = check.expectation
    search = (snapshot.get("alias_search") or {}).get(exp["q"])
    if search is None:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason=f"runner 未提供 alias_search[{exp['q']}]")
    hits = search.get("hits") or []
    if not hits:
        return CheckOutcome(check.id, OUTCOME_FAIL, reason=f"搜索 {exp['q']} 无命中")
    if len(hits) > 1:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"搜索 {exp['q']} 多命中 {len(hits)} 个 canonical",
                            actual={"hits": [h.get("name") for h in hits]})
    if hits[0].get("name") != exp["expected_name"]:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"搜索 {exp['q']} 命中 {hits[0].get('name')} ≠ {exp['expected_name']}",
                            actual={"hit": hits[0].get("name")})
    return CheckOutcome(check.id, OUTCOME_PASS, actual={"hit": hits[0].get("name")})


def _eval_count_eq(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """B1：snapshot.counts[key] == expected。"""
    exp = check.expectation
    counts = snapshot.get("counts") or {}
    if exp["key"] not in counts:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason=f"snapshot.counts 缺 {exp['key']}")
    val = counts[exp["key"]]
    if val != exp["expected"]:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"{exp['key']}={val} ≠ {exp['expected']}",
                            actual={"value": val, "expected": exp["expected"]})
    return CheckOutcome(check.id, OUTCOME_PASS, actual={"value": val})


def _eval_person_absent_and_not_alias(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """C1/C2：name 不得成为 Person，也不得被任何 canonical aliases 吸收（P16-b 拦截）。"""
    name = check.expectation["name"]
    if _person_named(snapshot, name):
        return CheckOutcome(check.id, OUTCOME_FAIL, reason=f"{name} 成为独立 Person",
                            actual={"person": name})
    absorbed = [p["name"] for p in snapshot.get("persons", [])
                if name in (p.get("aliases") or [])]
    if absorbed:
        return CheckOutcome(check.id, OUTCOME_FAIL, reason=f"{name} 被吸收进 {absorbed}",
                            actual={"absorbed_into": absorbed})
    return CheckOutcome(check.id, OUTCOME_PASS)


def _eval_aliases_not_contain(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """C4：person 的 aliases 不得含 forbidden 项（P16-b sink 收敛）。"""
    exp = check.expectation
    persons = _persons_by_mention(snapshot, exp["person"])
    if not persons:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason=f"{exp['person']} 未被提取（空洞防）")
    p = persons[0]
    aliases = p.get("aliases") or []
    bad = [f for f in exp["forbidden"] if f in aliases]
    if bad:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"{p['name']}.aliases 含禁止项 {bad}",
                            actual={"aliases": aliases, "forbidden_hits": bad})
    return CheckOutcome(check.id, OUTCOME_PASS, actual={"aliases": aliases})


def _eval_alias_in_aliases(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """C3：alias 必须 ∈ person.aliases（爹爹→顺顺 confirmed 证据机制实证）。"""
    exp = check.expectation
    persons = _persons_by_mention(snapshot, exp["person"])
    if not persons:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason=f"{exp['person']} 未被提取（空洞防）")
    p = persons[0]
    aliases = p.get("aliases") or []
    if exp["alias"] in aliases:
        return CheckOutcome(check.id, OUTCOME_PASS, actual={"aliases": aliases})
    return CheckOutcome(check.id, OUTCOME_FAIL,
                        reason=f"{exp['alias']} ∉ {p['name']}.aliases",
                        actual={"aliases": aliases})


def _eval_family_fragments(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """D1：家族碎片（大儿子/长子/次子/第二个儿子）不得独立 canonical，也不得错吸到家族外。"""
    exp = check.expectation
    family = set(exp["family"])
    if not any(_persons_by_mention(snapshot, m) for m in family):
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="家族成员未被提取（空洞防）")
    bad = []
    for f in exp["fragments"]:
        hits = _persons_by_mention(snapshot, f)
        if not hits:
            continue  # 未出现（未提取或已吸收）→ OK
        p = hits[0]
        if p["name"] == f:
            bad.append({"fragment": f, "canonical": f, "kind": "independent"})
        elif p["name"] not in family:
            bad.append({"fragment": f, "canonical": p["name"], "kind": "wrong_absorption"})
    if bad:
        return CheckOutcome(check.id, OUTCOME_FAIL, reason="家族碎片未收敛", actual={"fragments": bad})
    return CheckOutcome(check.id, OUTCOME_PASS)


def _eval_fragments_not_independent(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """D3：碎片词不得以独立 canonical 注册（D-9：无法确认的 DESCRIPTIVE 不注册）。"""
    present = [f for f in check.expectation["fragments"] if _person_named(snapshot, f)]
    if present:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"碎片以独立 canonical 注册: {present}",
                            actual={"fragments": present})
    return CheckOutcome(check.id, OUTCOME_PASS)


def _eval_record_stats(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """B2/D2/E1/G2/G4：记录统计值（observation，永不判败）。"""
    keys = check.expectation["keys"]
    actual = {k: _stats_get(stats, k) for k in keys}
    if not any(v is not None for v in actual.values()):
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="stats 缺全部记录键")
    return CheckOutcome(check.id, OUTCOME_OBSERVATION, actual=actual)


def _eval_merge_observation(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """F1：merge stats 记录；全部 failed → INCONCLUSIVE（非 FAIL，P11/merge 域）。"""
    merge = stats.get("merge")
    if not isinstance(merge, dict):
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="stats 缺 merge 数据")
    actual = {k: merge.get(k, 0) for k in
              ("merge_candidate_pairs", "merged_pairs", "rejected_pairs",
               "low_confidence_pairs", "failed_pairs")}
    total = actual["merge_candidate_pairs"]
    failed = actual["failed_pairs"]
    if total > 0 and failed >= total:
        return CheckOutcome(check.id, OUTCOME_INCONCLUSIVE,
                            reason="merge judge 全部失败（INCONCLUSIVE，非 FAIL）", actual=actual)
    return CheckOutcome(check.id, OUTCOME_OBSERVATION, actual=actual)


def _eval_observation_if_person(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """C5：记录 name 是否成为独立 Person / 被谁吸收（D5 Known Limitation，记录不判败）。"""
    name = check.expectation["name"]
    persons = _person_named(snapshot, name)
    absorbed = [p["name"] for p in snapshot.get("persons", [])
                if name in (p.get("aliases") or [])]
    return CheckOutcome(check.id, OUTCOME_OBSERVATION,
                        actual={"person": bool(persons), "absorbed_into": absorbed})


def _eval_labels_subset(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """G1：本 novel 子图 labels ⊆ 白名单（D-3 数据模型边界）。"""
    labels = snapshot.get("labels_used")
    if labels is None:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="snapshot 缺 labels_used")
    extra = sorted(set(labels) - set(check.expectation["allowed"]))
    if extra:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"出现非白名单标签 {extra}",
                            actual={"labels": sorted(labels)})
    return CheckOutcome(check.id, OUTCOME_PASS, actual={"labels": sorted(labels)})


def _eval_novel_isolation(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """G3：采样到的 novel_id 必须全部 == 本 run novel_id（D-2 隔离）。"""
    seen = snapshot.get("novel_ids_seen")
    if seen is None:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="snapshot 缺 novel_ids_seen")
    nid = snapshot.get("novel_id")
    foreign = sorted({s for s in seen if s != nid})
    if foreign:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason=f"跨 novel 数据 {foreign}",
                            actual={"seen": sorted(seen)})
    return CheckOutcome(check.id, OUTCOME_PASS, actual={"novel_id": nid})


def _eval_no_checkpoint_dir(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """G5：eval 运行不得产生 checkpoint 目录（P19 checkpoint 语义零改动守卫）。"""
    exists = snapshot.get("checkpoint_dir_exists")
    if exists is None:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason="snapshot 缺 checkpoint_dir_exists")
    if exists:
        return CheckOutcome(check.id, OUTCOME_FAIL,
                            reason="该 novel 产生了 checkpoint 目录（P19 语义被触碰）")
    return CheckOutcome(check.id, OUTCOME_PASS)


_EVALUATORS: dict[str, Callable[[CheckDef, dict, dict], CheckOutcome]] = {
    "single_canonical_with_aliases": _eval_single_canonical_with_aliases,
    "aliased_into": _eval_aliased_into,
    "distinct_persons": _eval_distinct_persons,
    "alias_search_unique": _eval_alias_search_unique,
    "count_eq": _eval_count_eq,
    "person_absent_and_not_alias": _eval_person_absent_and_not_alias,
    "aliases_not_contain": _eval_aliases_not_contain,
    "alias_in_aliases": _eval_alias_in_aliases,
    "family_fragments": _eval_family_fragments,
    "fragments_not_independent": _eval_fragments_not_independent,
    "record_stats": _eval_record_stats,
    "merge_observation": _eval_merge_observation,
    "observation_if_person": _eval_observation_if_person,
    "labels_subset": _eval_labels_subset,
    "novel_isolation": _eval_novel_isolation,
    "no_checkpoint_dir": _eval_no_checkpoint_dir,
}


# ---------------------------------------------------------------------------
# 判定入口（纯函数）
# ---------------------------------------------------------------------------


def evaluate_check(check: CheckDef, snapshot: dict, stats: dict) -> CheckOutcome:
    """单条检查判定：前置条件（空洞防）→ kind evaluator。不含 G4（编排层处理）。"""
    ok, cond = _preconditions_met(check, snapshot)
    if not ok:
        return CheckOutcome(check.id, OUTCOME_SKIP, reason=f"前置不满足: {cond}（空洞防）")
    fn = _EVALUATORS.get(check.expectation.get("kind"))
    if fn is None:
        return CheckOutcome(check.id, OUTCOME_INCONCLUSIVE,
                            reason=f"未知 kind: {check.expectation.get('kind')!r}")
    return fn(check, snapshot, stats)


def evaluate_checkset(checkset: CheckSet, snapshot: dict, stats: dict) -> list[CheckOutcome]:
    """整集判定（含 G4 降级，Spec §4.2 G4 / §7.1）：

    - 存在失败 chunk 且检查需要全语料证据（needs_full_corpus）且可产生决定性结果
      （非记录型）→ INCONCLUSIVE（证据可能缺失，不允许假 PASS/FAIL）；
    - 记录型检查（observation）不被 G4 降级——趋势数据照常记录。
    """
    failed = _failed_chunk_ids(stats)
    outcomes = []
    for check in checkset.checks:
        if failed and check.needs_full_corpus and not check.is_record:
            outcomes.append(CheckOutcome(
                check.id, OUTCOME_INCONCLUSIVE,
                reason=f"G4 降级：failed_chunks={failed}，检查需要全语料证据",
                actual={"failed_chunks": failed}))
        else:
            outcomes.append(evaluate_check(check, snapshot, stats))
    return outcomes


def validate_checkset(checkset: CheckSet) -> list[str]:
    """checkset 结构校验（--dry-run 与测试使用）：返回错误列表，空 = 合法。"""
    errors: list[str] = []
    ids = [c.id for c in checkset.checks]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append(f"check id 重复: {dup}")
    for c in checkset.checks:
        if c.expectation.get("kind") not in _EVALUATORS:
            errors.append(f"[{c.id}] 未知 kind: {c.expectation.get('kind')!r}")
        if c.outcome_class not in (_CLASS_STABLE, _CLASS_VARIANCE, _CLASS_OBSERVATION):
            errors.append(f"[{c.id}] outcome_class 非法: {c.outcome_class!r}")
        if not c.attribution:
            errors.append(f"[{c.id}] 缺 attribution（修改期望=修改决策，必须声明归属）")
        if not c.layer:
            errors.append(f"[{c.id}] 缺 layer（PIPELINE_LAYER §4 归因链）")
        for cond in (*c.preconditions, *c.precondition_any):
            if not cond.startswith("person_exists:"):
                errors.append(f"[{c.id}] 未知前置条件: {cond!r}")
    return errors


# ---------------------------------------------------------------------------
# checkset v1（Spec §4.2 检查清单；内容修改必须 bump checkset_version）
# ---------------------------------------------------------------------------

_CORPUS_边城 = {
    "name": "边城",
    "path": "books/边城_(沈从文)_(z-library.sk,_1lib.sk,_z-lib.sk).epub",
    # sha256(EPUB bytes)；run 时由 runner 重新计算并校验一致（compare_identity.corpus_hash）
    "content_hash": "1293b0befe978e0b7a3ab6358b8616bb191693f6ff1e9549c4e541ee21b73aae",
}

_FRAGMENT_NAMES = ("大儿子", "长子", "次子", "第二个儿子")   # P017 ch5b 一族碎片词（TESTING §9.1）
_FAMILY_MEMBERS = ("天保", "傩送", "大老", "二老")          # ch5b 一族目标 canonical 域

CHECKSET_V1 = CheckSet(
    schema_version=1,
    checkset_version="1",
    applies_to="V0.2.5+（冻结语义集，Spec §4.2）",
    corpus=_CORPUS_边城,
    checks=(
        # ---- A 正向合并（TESTING.md §4）----
        CheckDef("A1", "正向合并", "傩送/二老/老二 归并为同一 canonical，aliases 含其余名",
                 {"kind": "single_canonical_with_aliases",
                  "members": ("傩送", "二老", "老二"),
                  "alias_contains": ("二老", "老二")},
                 outcome_class=_CLASS_VARIANCE, attribution="P08 / D-4", layer="merge"),
        CheckDef("A2", "正向合并", "天保/大老 归并为同一 canonical，aliases 含其余名",
                 {"kind": "single_canonical_with_aliases",
                  "members": ("天保", "大老"),
                  "alias_contains": ("大老",)},
                 outcome_class=_CLASS_VARIANCE, attribution="P08 / D-4", layer="merge"),
        CheckDef("A3", "正向合并", "老船夫 不独立 canonical，吸收进 祖父.aliases",
                 {"kind": "aliased_into", "alias": "老船夫", "target": "祖父"},
                 outcome_class=_CLASS_STABLE, attribution="P08 / D-4", layer="merge"),
        CheckDef("A4", "正向合并", "爷爷 → 祖父 alias（P06 波动）",
                 {"kind": "aliased_into", "alias": "爷爷", "target": "祖父"},
                 outcome_class=_CLASS_VARIANCE, attribution="P06", layer="judge"),
        CheckDef("A5", "正向合并", "负向：傩送 与 杨马兵 不得合并",
                 {"kind": "distinct_persons", "a": "傩送", "b": "杨马兵"},
                 needs_full_corpus=False,
                 outcome_class=_CLASS_STABLE, attribution="P08 / D-4", layer="merge"),
        CheckDef("A6", "正向合并", "alias 搜索 q=二老 唯一命中 canonical=傩送",
                 {"kind": "alias_search_unique", "q": "二老", "expected_name": "傩送"},
                 outcome_class=_CLASS_VARIANCE, attribution="D-2", layer="registration"),

        # ---- B 非正文（V0.2.5-a，P016）----
        CheckDef("B1", "非正文", "非正文 canonical 数量 == 0",
                 {"kind": "count_eq", "key": "nonbody_canonical_count", "expected": 0},
                 needs_full_corpus=False,
                 outcome_class=_CLASS_STABLE, attribution="P016", layer="admission"),
        CheckDef("B2", "非正文", "provisional → promoted/dropped 计数（observation）",
                 {"kind": "record_stats", "keys": ("hygiene.nonbody_person_provisional",
                                                   "hygiene.nonbody_provisional_dropped",
                                                   "hygiene.nonbody_descriptive_dropped")},
                 outcome_class=_CLASS_OBSERVATION, attribution="P016", layer="admission"),

        # ---- C P16-b / P18 冻结（D-5 / D-6）----
        CheckDef("C1", "P16-b/P18", "父亲 不得成为 Person，也不得被任何 aliases 吸收（前置：顺顺 存在）",
                 {"kind": "person_absent_and_not_alias", "name": "父亲"},
                 preconditions=("person_exists:顺顺",), needs_full_corpus=False,
                 outcome_class=_CLASS_STABLE, attribution="D-5 / D-6", layer="admission"),
        CheckDef("C2", "P16-b/P18", "翠翠的父亲 不得被任何 aliases 吸收（qualified 拦截）",
                 {"kind": "person_absent_and_not_alias", "name": "翠翠的父亲"},
                 precondition_any=("person_exists:翠翠", "person_exists:翠翠的父亲"),
                 needs_full_corpus=False,
                 outcome_class=_CLASS_STABLE, attribution="D-5", layer="admission"),
        CheckDef("C3", "P16-b/P18", "爹爹 ∈ 顺顺.aliases（≥2 独立证据 → confirmed 机制实证）",
                 {"kind": "alias_in_aliases", "person": "顺顺", "alias": "爹爹"},
                 preconditions=("person_exists:顺顺",),
                 outcome_class=_CLASS_VARIANCE, attribution="D-5", layer="admission"),
        CheckDef("C4", "P16-b/P18", "顺顺.aliases 不含 父亲/爸爸（sink 收敛；爸爸 波动归 D5）",
                 {"kind": "aliases_not_contain", "person": "顺顺",
                  "forbidden": ("父亲", "爸爸")},
                 preconditions=("person_exists:顺顺",),
                 outcome_class=_CLASS_VARIANCE, attribution="D-6 / P018", layer="admission"),
        CheckDef("C5", "P16-b/P18", "爸爸 独立 Person → OBSERVATION（D5 Known Limitation，非 FAIL）",
                 {"kind": "observation_if_person", "name": "爸爸"},
                 outcome_class=_CLASS_OBSERVATION, attribution="D-10 / P017-D5", layer="registration"),

        # ---- D P17 / D-9 ----
        CheckDef("D1", "P17/D-9", "ch5b 家族碎片（大儿子/长子/次子/第二个儿子）不独立 canonical、不错吸家族外",
                 {"kind": "family_fragments", "fragments": _FRAGMENT_NAMES,
                  "family": _FAMILY_MEMBERS},
                 outcome_class=_CLASS_VARIANCE, attribution="P017 / D-9", layer="registration"),
        CheckDef("D2", "P17/D-9", "descriptive/composite resolved/unresolved 计数（observation；趋势）",
                 {"kind": "record_stats", "keys": ("hygiene.descriptive_resolved",
                                                   "hygiene.descriptive_unresolved",
                                                   "hygiene.composite_resolved",
                                                   "hygiene.composite_unresolved")},
                 outcome_class=_CLASS_OBSERVATION, attribution="P017 / P06", layer="registration"),
        CheckDef("D3", "P17/D-9", "碎片词不得以独立 canonical 注册（D-9：无法确认的 DESCRIPTIVE 不注册）",
                 {"kind": "fragments_not_independent", "fragments": _FRAGMENT_NAMES},
                 outcome_class=_CLASS_STABLE, attribution="D-9", layer="registration"),

        # ---- E P09 hygiene ----
        CheckDef("E1", "P09", "collective/generic/invalid 过滤计数（observation；趋势）",
                 {"kind": "record_stats", "keys": ("hygiene.collective_filtered",
                                                   "hygiene.generic_filtered",
                                                   "hygiene.invalid_filtered")},
                 outcome_class=_CLASS_OBSERVATION, attribution="P09", layer="hygiene"),

        # ---- F merge ----
        CheckDef("F1", "merge", "merge stats 记录；全部 failed → INCONCLUSIVE（非 FAIL）",
                 {"kind": "merge_observation"},
                 outcome_class=_CLASS_OBSERVATION, attribution="P11", layer="merge"),

        # ---- G 数据安全与图完整性 ----
        CheckDef("G1", "数据安全", "本 novel 子图 labels ⊆ {Novel, Person}（D-3 边界）",
                 {"kind": "labels_subset", "allowed": ("Novel", "Person")},
                 needs_full_corpus=False,   # 结构/隔离检查：不依赖 chunk-level extraction 证据（Step 5.1）
                 outcome_class=_CLASS_STABLE, attribution="D-3", layer="db"),
        CheckDef("G2", "数据安全", "persons / relationships 计数记录",
                 {"kind": "record_stats", "keys": ("counts.persons", "counts.relationships")},
                 outcome_class=_CLASS_OBSERVATION, attribution="D-2 / TESTING.md §5", layer="db"),
        CheckDef("G3", "数据安全", "无跨 novel 污染（采样 novel_id 全部 == 本 run novel_id）",
                 {"kind": "novel_isolation"},
                 needs_full_corpus=False,   # 结构/隔离检查：不依赖 chunk-level extraction 证据（Step 5.1）
                 outcome_class=_CLASS_STABLE, attribution="D-2 / D-3", layer="db"),
        CheckDef("G4", "数据安全", "failed_blocks 记录 + 失败 chunk 覆盖检查降级（G4 规则）",
                 {"kind": "record_stats", "keys": ("failed_blocks",)},
                 outcome_class=_CLASS_OBSERVATION, attribution="P04 / P05 / P13", layer="infra"),
        CheckDef("G5", "数据安全", "eval 运行不得产生 checkpoint 目录（P19 语义零改动守卫）",
                 {"kind": "no_checkpoint_dir"},
                 needs_full_corpus=False,
                 outcome_class=_CLASS_STABLE, attribution="P19（约束 1）", layer="checkpoint"),
    ),
)
