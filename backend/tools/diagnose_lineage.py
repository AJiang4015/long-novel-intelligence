"""V0.2.7 Task A：lineage JSONL 离线归层诊断工具（不参与运行时业务逻辑）。

只读取 LineageRecorder 落盘的 <ER_LINEAGE_DIR>/<novel_id>.jsonl，按 lineage_id 归组，
沿固定决策序 extraction → category → recall → judge → admission → registration → merge，
为每个目标 mention 输出**唯一故障层**（或明确多层并存）与**决定性证据**。

用法（backend 目录下）：
    python tools/diagnose_lineage.py lineage/<novel_id>.jsonl \
        --mention 翠翠的祖父 --mention 岳云二老 --mention 弟弟 --mention 爷爷 \
        --expect 翠翠的祖父=祖父 --expect 岳云二老=傩送 --expect 弟弟=二老 --expect 爷爷=祖父
    python tools/diagnose_lineage.py lineage/<novel_id>.jsonl --mention 翠翠的祖父   # 不带 expect：输出事实链 + 终态
    python tools/diagnose_lineage.py lineage/<novel_id>.jsonl --all                 # 全部 mention 一行概览

故障层取值：
  SUCCESS / SUCCESS_ALIAS / SUCCESS_CANONICAL   达到期望（或无期望时的成功终态）
  EXTRACTION_LAYER          mention 未出现在任何 chunk 的 extraction 输出（LLM 未提取）
  CATEGORY_LAYER_D5         extraction_category=None/PERSON → 未标 DESCRIPTIVE → 绕过 evidence gate（P017 D5）
  RECALL_LAYER              recall_candidates 全空 → 无候选可 judge（P08）
  JUDGE_LAYER               judge 判 null / missing / 异常（P06）
  ADMISSION_LAYER           P16-b gate 拒绝（reject/observation/blocked，附 reason）
  HYGIENE_LAYER             skipped_generic / skipped_hardfilter / nonbody_dropped 丢弃
  MERGE_LAYER               最终 canonical 被 merge_map 吸收（C_drop）
  REGISTRATION_LAYER        注册为自身 canonical 而未达期望 alias
  CHAIN_BREAK               事件缺失（记录缺口 / 失败 chunk，附 failed_blocks 对照）
  UNKNOWN                   事实链不足以归层

本模块只依赖标准库（json/argparse/collections），不 import app.*（轻量离线工具）。
"""
import argparse
import json
from collections import defaultdict

# 固定决策序（spec §6）：任一层的决定性事实出现即归层，否则沿链下探
LAYER_ORDER = ["extraction", "category", "recall", "judge", "admission", "registration", "merge"]

_TERMINAL_NEGATIVE_ADMISSIONS = ("reject", "observation", "blocked")
_HYGIENE_ADMISSIONS = ("skipped_generic", "skipped_hardfilter", "nonbody_dropped")


def load_events(path: str) -> list[dict]:
    events: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _failed_chunks(events: list[dict]) -> list[int]:
    for e in events:
        if e.get("event") == "job_end":
            return [fb.get("chunk_id") for fb in e.get("failed_blocks", []) if fb.get("chunk_id")]
    return []


def _raw_extraction_has(events: list[dict], mention: str) -> tuple[bool, int | None]:
    """extraction_raw（ER_LINEAGE_RAW_EXTRACTION=1 时）中 mention 是否出现。"""
    for e in events:
        if e.get("event") != "extraction_raw":
            continue
        chars = e.get("characters", [])
        rels = e.get("relationships", [])
        names = [c.get("name") for c in chars]
        names += [r.get("source") for r in rels] + [r.get("target") for r in rels]
        if mention in names:
            return True, e.get("chunk_id")
    return False, None


def _merge_drops(events: list[dict]) -> dict[str, str]:
    return {e.get("canonical"): e.get("merge_keep") for e in events if e.get("event") == "merge_drop"}


def _effective_category(enter: dict) -> str | None:
    """hygiene 强制类别优先（generic/collective/invalid），否则用 LLM category。"""
    hy = enter.get("hygiene_category")
    if hy in ("generic", "collective", "invalid"):
        return hy
    return enter.get("extraction_category")


def _chains_text(lines: list[dict]) -> list[str]:
    """按 lineage_id 归组 → 逐层证据链文本。"""
    by_lineage: dict[str, list[dict]] = defaultdict(list)
    for e in lines:
        by_lineage[e.get("lineage_id")].append(e)
    segs: list[str] = []
    for lid in sorted(by_lineage, key=lambda x: by_lineage[x][0].get("chunk_id", 0)):
        evs = by_lineage[lid]
        first = evs[0]
        segs.append(f"  lineage {lid[:8]} (chunk {first.get('chunk_id')}, ch {first.get('chapter_id')}, "
                    f"{first.get('section_type')})")
        for e in evs:
            ev = e.get("event")
            if ev == "mention_enter":
                segs.append(f"    [① extraction] extracted={e.get('extracted')} "
                            f"extraction_category={e.get('extraction_category')} "
                            f"hygiene_category={e.get('hygiene_category')} roles={e.get('extraction_roles')}")
            elif ev == "recall":
                segs.append(f"    [② recall] source={e.get('recall_source')} "
                            f"candidates={e.get('recall_candidates')} "
                            f"role={e.get('role_kind')}/{e.get('role_anchor')}/{e.get('role_headword')}")
            elif ev == "judge":
                segs.append(f"    [③ judge] called={e.get('judge_called')} "
                            f"resolves_to={e.get('judge_resolves_to')} missing={e.get('judge_missing')} "
                            f"error={e.get('judge_error')} batch={e.get('judge_input_mentions_count')} "
                            f"input_candidates={e.get('judge_input_candidates')}")
            elif ev == "admission":
                segs.append(f"    [④ admission] {e.get('admission')} reason={e.get('admission_reason')} "
                            f"evidence={e.get('evidence_count')} confirmed={e.get('role_confirmed')} "
                            f"blocked={e.get('role_blocked')}")
            elif ev == "registration":
                segs.append(f"    [⑤ registration] registered={e.get('registered')} "
                            f"alias_to={e.get('alias_to')} final_canonical={e.get('final_canonical')} "
                            f"provisional={e.get('provisional')}")
    return segs


def diagnose_mention(events: list[dict], mention: str,
                     expect: str | None = None) -> tuple[str, list[str], list[str]]:
    """返回 (verdict, 证据链文本行, notes)。verdict = 唯一故障层 / SUCCESS*。"""
    lines = [e for e in events if e.get("mention") == mention]
    failed_chunks = _failed_chunks(events)
    raw_hit, raw_chunk = _raw_extraction_has(events, mention)
    merge_drops = _merge_drops(events)

    # ---- 无任何 mention 事件：extraction 层或链路断点 ----
    if not lines:
        if raw_hit:
            return ("CHAIN_BREAK",
                    [f"extraction_raw 含该 mention（chunk {raw_chunk}）但无任何 lineage 事件——记录缺口"],
                    [f"failed chunks: {failed_chunks}"])
        if failed_chunks:
            return ("CHAIN_BREAK",
                    [f"job 有失败块 {failed_chunks}；mention 无任何 lineage 事件"],
                    ["若其原文所在 chunk 失败则为 chunk 层（内容损失）；否则 extraction 层（未提取）。"
                     "建议 ER_LINEAGE_RAW_EXTRACTION=1 复核"])
        return ("EXTRACTION_LAYER",
                ["无任何 lineage 事件 → mention 未出现在任何 chunk 的 extraction 输出"],
                ["LLM 未提取该 mention；或 extraction 输出被 hygiene 硬过滤（此时应有 skipped_hardfilter 事件）"])

    chain = _chains_text(lines)
    notes: list[str] = []

    enters = [e for e in lines if e.get("event") == "mention_enter"]
    all_recalls = [e for e in lines if e.get("event") == "recall"]
    all_judges = [e for e in lines if e.get("event") == "judge"]
    all_admissions = [e for e in lines if e.get("event") == "admission"]
    regs = [e for e in lines if e.get("event") == "registration"]
    last_reg = regs[-1] if regs else None

    registered = bool(last_reg and last_reg.get("registered"))
    actual_alias = last_reg.get("alias_to") if (registered and last_reg.get("alias_to")) else None
    actual_canonical = last_reg.get("final_canonical") if (registered and not actual_alias) else None
    merge_target = actual_alias or actual_canonical
    merge_absorbed = bool(merge_target and merge_target in merge_drops)

    def _fixed_order_verdict(reason_hint: str) -> tuple[str | None, list[str]]:
        """沿固定决策序找首个决定性负事实；返回 (verdict, notes)。"""
        n: list[str] = []
        # ① extraction：mention 有事件 → 已过 extraction 层
        # ② category：effective category ∈ {None, person} → D5（gate 无触发机会）
        eff_cats = {_effective_category(e) for e in enters}
        if eff_cats & {None, "person"}:
            n.append(f"effective category ∈ {sorted(str(c) for c in eff_cats)} → 未标 DESCRIPTIVE → "
                     f"绕过 evidence gate（P017 D5）[{reason_hint}]")
            return "CATEGORY_LAYER_D5", n
        # ③ recall：全部 recall 无候选
        if all_recalls and all(not (r.get("recall_candidates") or []) for r in all_recalls):
            n.append(f"recall_candidates 全空 → 无候选可 judge（P08）[{reason_hint}]")
            return "RECALL_LAYER", n
        # ④ judge：judge 被调用且 resolves_to null（missing/error 同归）
        null_judges = [j for j in all_judges
                       if j.get("judge_called") and j.get("judge_resolves_to") is None]
        if null_judges:
            jerr = null_judges[-1].get("judge_error")
            n.append(f"judge 判 null（missing={null_judges[-1].get('judge_missing')}, "
                     f"error={jerr}）→ 候选存在但未消歧（P06）[{reason_hint}]")
            return "JUDGE_LAYER", n
        # ⑤ admission：gate 拒绝
        rej = [a for a in all_admissions if a.get("admission") in _TERMINAL_NEGATIVE_ADMISSIONS]
        if rej:
            last = rej[-1]
            n.append(f"gate 拒绝：{last.get('admission')}/{last.get('admission_reason')} "
                     f"evidence={last.get('evidence_count')} blocked={last.get('role_blocked')} "
                     f"[{reason_hint}]")
            return "ADMISSION_LAYER", n
        # ⑥ merge：最终 canonical 被 merge_map 吸收
        if merge_absorbed:
            n.append(f"{merge_target} ∈ merge_map → {merge_drops[merge_target]}（C_drop）[{reason_hint}]")
            return "MERGE_LAYER", n
        return None, n

    if expect:
        expected = expect
        if actual_alias == expected or actual_canonical == expected:
            return "SUCCESS", chain, notes + [f"期望满足：{mention} → {expected}"]
        verdict, n = _fixed_order_verdict(f"期望 alias → {expected}")
        if verdict:
            return verdict, chain, notes + n
        if registered and actual_canonical and actual_canonical != expected:
            notes.append(f"注册为自身 canonical {actual_canonical}（期望 alias {expected}）")
            return "REGISTRATION_LAYER", chain, notes
        return "UNKNOWN", chain, notes + ["事实链不足以归层"]

    # ---- 无 expect：报告成功终态或首个决定性负事实 ----
    if registered and actual_alias:
        return "SUCCESS_ALIAS", chain, notes + [f"registered alias → {actual_alias}"]
    if registered and actual_canonical:
        return "SUCCESS_CANONICAL", chain, notes + [f"registered canonical {actual_canonical}（无期望对比）"]
    verdict, n = _fixed_order_verdict("未注册")
    if verdict:
        return verdict, chain, notes + n
    if all_admissions:
        last_adm = all_admissions[-1]
        if last_adm.get("admission") in _HYGIENE_ADMISSIONS:
            notes.append(f"dropped：{last_adm.get('admission')}/{last_adm.get('admission_reason')}")
            return "HYGIENE_LAYER", chain, notes
        notes.append(f"terminal admission：{last_adm.get('admission')}/{last_adm.get('admission_reason')}")
        return "ADMISSION_LAYER", chain, notes
    return "UNKNOWN", chain, notes + ["事实链不足以归层"]


def _all_mentions(events: list[dict]) -> list[str]:
    seen: set[str] = set()
    for e in events:
        m = e.get("mention")
        if m:
            seen.add(m)
    return sorted(seen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="lineage JSONL 离线归层诊断（Task A 验收工具；只读，不参与运行时业务逻辑）")
    ap.add_argument("file", help="lineage JSONL 文件（<ER_LINEAGE_DIR>/<novel_id>.jsonl）")
    ap.add_argument("--mention", action="append", default=[], help="目标 mention（可多次）")
    ap.add_argument("--expect", action="append", default=[],
                    help="期望归并，如 翠翠的祖父=祖父（可多次）")
    ap.add_argument("--all", action="store_true", help="输出全部 mention 一行概览（不逐链）")
    args = ap.parse_args(argv)

    events = load_events(args.file)
    expects: dict[str, str] = {}
    for kv in args.expect:
        key, _, val = kv.partition("=")
        expects[key.strip()] = val.strip()

    mentions = list(dict.fromkeys(args.mention + list(expects)))
    if not mentions and not args.all:
        ap.error("至少需要 --mention / --expect 之一（或 --all）")

    if args.all:
        print(f"{'mention':<20} {'verdict':<22} evidence")
        for m in _all_mentions(events):
            verdict, _chain, notes = diagnose_mention(events, m, expects.get(m))
            ev = notes[-1] if notes else ""
            print(f"{m:<20} {verdict:<22} {ev}")

    for m in mentions:
        expect = expects.get(m)
        verdict, chain, notes = diagnose_mention(events, m, expect)
        print(f"=== {m} ==={'（期望 → ' + expect + '）' if expect else ''}")
        for line in chain:
            print(line)
        for note in notes:
            print(f"  note: {note}")
        print(f"verdict: {verdict}")
        print()
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
