"""V0.2.7 Task A：P06 lineage 观测测试（deterministic，mock judge）。

覆盖（对应 Task A 评审 4 约束）：
- recorder：enabled 字段收集 + flush JSONL（mention 事件必带 lineage_id）；disabled no-op（零事件）
- resolver + lineage：判定输出与无 lineage 完全一致（零行为变更，207 基线不回归）
- 全层 lineage_id 关联：extraction/recall/judge/admission/registration 事件共享同一 lineage_id
- 各分支事件：known_hit / bare role observation→confirmed / deferred→unresolved / judge exception
- diagnose_lineage 离线归层：四历史案例合成 JSONL（judge null / D5 / target mismatch / generic
  / merge / 未提取 / 失败块 / 成功）
- config：ER_LINEAGE / ER_LINEAGE_RAW_EXTRACTION 默认全关
"""
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.chunker import Chunk
from app.pipeline.lineage import LineageRecorder, create_lineage_recorder
from app.pipeline.resolver import EntityResolver
from app.pipeline.sections import SectionType
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MentionCategory

from tools.diagnose_lineage import diagnose_mention, load_events

P = MentionCategory.PERSON
D = MentionCategory.DESCRIPTIVE
C = MentionCategory.COMPOSITE

BAILIAN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# P12 沙箱限制：pytest tmp_path（mode=0o700）目录会被沙箱锁定 → 自建工作区 .tmp 目录
# （默认 mode 可写；.tmp/ 已 gitignore，评估脚本同样约定在此落盘）。
_REPO_TMP = Path(__file__).resolve().parents[2] / ".tmp" / "lineage-tests"


@pytest.fixture
def ws_tmp():
    d = _REPO_TMP / uuid.uuid4().hex[:12]
    os.makedirs(d, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_chunk(chunk_id, text="文本", section_type=SectionType.BODY):
    return Chunk(chunk_id=chunk_id, chapter_id=chunk_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text), section_type=section_type)


def extraction(names, categories=None):
    chars = []
    for n in names:
        item = {"name": n}
        if categories and categories.get(n) is not None:
            item["category"] = categories[n].value
        chars.append(item)
    return ExtractionResult.model_validate({"characters": chars, "relationships": []})


def judge_resolves(mapping):
    """mock judge：mention -> resolves_to canonical（缺省 null）。"""
    def j(text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": mapping.get(p.mention)} for p in pending]})
    return j


def enabled_recorder(ws_tmp, novel="n1", job="j1"):
    return LineageRecorder(enabled=True, novel_id=novel, job_id=job,
                           raw_extraction=False, out_dir=str(ws_tmp))


def events_of(recorder):
    return list(recorder._events)


def write_jsonl(ws_tmp, events):
    p = ws_tmp / "lineage.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return str(p)


# ---------- recorder 本体 ----------

def test_recorder_disabled_is_noop():
    r = LineageRecorder(enabled=False)
    r.chunk_start(chunk_id=1, chapter_id=1, section_type="body", text_len=5,
                  characters_count=1, relationships_count=0)
    r.mention_enter(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body",
                    mention="x", extracted=True, extraction_category="descriptive",
                    hygiene_category=None, extraction_roles=["character"])
    r.recall(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="x",
             role_kind="bare", role_has_de=False, role_anchor=None, role_anchor_known=False,
             role_headword=None, recall_source="none", recall_candidates=[])
    r.judge(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="x",
            judge_called=True, judge_input_mentions_count=1, judge_input_candidates=None,
            judge_resolves_to=None, judge_missing=False, judge_error=None)
    r.admission(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="x",
                admission="accept", admission_reason=None, evidence_count=None,
                role_confirmed=False, role_blocked=False)
    r.registration(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="x",
                   registered=True, alias_to=None, final_canonical="x", provisional=False)
    assert len(r) == 0
    assert r.flush() is None


def test_recorder_collects_and_flushes_jsonl(ws_tmp):
    r = enabled_recorder(ws_tmp)
    r.mention_enter(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body",
                    mention="翠翠的祖父", extracted=True, extraction_category="descriptive",
                    hygiene_category=None, extraction_roles=["character"])
    r.recall(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="翠翠的祖父",
             role_kind="qualified", role_has_de=True, role_anchor="翠翠", role_anchor_known=True,
             role_headword="祖父", recall_source="strong_extraction", recall_candidates=["祖父"])
    r.judge(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="翠翠的祖父",
            judge_called=True, judge_input_mentions_count=1, judge_input_candidates=["祖父"],
            judge_resolves_to="祖父", judge_missing=False, judge_error=None)
    r.admission(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="翠翠的祖父",
                admission="accept", admission_reason=None, evidence_count=None,
                role_confirmed=False, role_blocked=False)
    r.registration(lineage_id="L1", chunk_id=1, chapter_id=1, section_type="body", mention="翠翠的祖父",
                   registered=True, alias_to="祖父", final_canonical="祖父", provisional=False)
    path = r.flush()
    assert path is not None and path.exists()
    evs = [json.loads(x) for x in path.read_text(encoding="utf-8").strip().splitlines()]
    assert len(evs) == 5
    assert all(e["lineage_id"] == "L1" for e in evs)          # 全层 lineage_id 一致
    assert evs[0]["event"] == "mention_enter" and evs[0]["mention"] == "翠翠的祖父"
    assert evs[-1]["event"] == "registration" and evs[-1]["alias_to"] == "祖父"


# ---------- resolver 打点：零行为变更 ----------

def test_resolver_with_lineage_does_not_change_decisions(ws_tmp):
    chunks = [
        (make_chunk(1, text="翠翠"), extraction(["翠翠"], {"翠翠": P})),
        (make_chunk(2, text="翠翠祖父"),
         extraction(["祖父", "翠翠的祖父"], {"祖父": P, "翠翠的祖父": D})),
    ]
    judge = judge_resolves({"翠翠的祖父": "祖父"})
    r_plain = EntityResolver(judge=judge)
    r_lg = EntityResolver(judge=judge, lineage=enabled_recorder(ws_tmp))
    out_plain, fail_plain = [], []
    for ch, ex in chunks:
        o, f = r_plain.resolve(ch, ex)
        out_plain.append(o.model_dump())
        fail_plain.append(f)
    out_lg, fail_lg = [], []
    for ch, ex in chunks:
        o, f = r_lg.resolve(ch, ex)
        out_lg.append(o.model_dump())
        fail_lg.append(f)
    assert out_plain == out_lg
    assert fail_plain == fail_lg
    assert r_plain.known == r_lg.known
    assert r_plain.canonical_aliases == r_lg.canonical_aliases
    assert r_plain.hygiene_stats == r_lg.hygiene_stats


# ---------- resolver 打点：全层 lineage_id 关联 + 字段 ----------

def test_lineage_events_joined_by_lineage_id(ws_tmp):
    r = EntityResolver(judge=judge_resolves({"翠翠的祖父": "祖父"}),
                       lineage=enabled_recorder(ws_tmp))
    # chunk1：翠翠/祖父 成为 known（祖父 经 judge null → null_registered fallback）
    r.resolve(make_chunk(1, text="翠翠祖父"),
              extraction(["翠翠", "祖父"], {"翠翠": P, "祖父": P}))
    # chunk2：翠翠的祖父 qualified → 强文本共现召回 [翠翠, 祖父] → judge → 祖父 → alias
    r.resolve(make_chunk(2, text="翠翠祖父"), extraction(["翠翠的祖父"], {"翠翠的祖父": D}))
    evs = events_of(r._lineage)
    me = [e for e in evs if e["event"] == "mention_enter" and e["mention"] == "翠翠的祖父"]
    rc = [e for e in evs if e["event"] == "recall" and e["mention"] == "翠翠的祖父"]
    jg = [e for e in evs if e["event"] == "judge" and e["mention"] == "翠翠的祖父"]
    ad = [e for e in evs if e["event"] == "admission" and e["mention"] == "翠翠的祖父"]
    rg = [e for e in evs if e["event"] == "registration" and e["mention"] == "翠翠的祖父"]
    assert len(me) == 1 and len(rc) == 1 and len(jg) == 1 and len(ad) == 1 and len(rg) == 1
    lids = {me[0]["lineage_id"], rc[0]["lineage_id"], jg[0]["lineage_id"],
            ad[0]["lineage_id"], rg[0]["lineage_id"]}
    assert len(lids) == 1                       # 五层共享同一 lineage_id
    assert me[0]["extraction_category"] == "descriptive"
    assert "祖父" in rc[0]["recall_candidates"]
    assert rc[0]["recall_source"] == "strong_text"
    assert rc[0]["role_kind"] == "qualified" and rc[0]["role_anchor"] == "翠翠"
    assert rc[0]["role_headword"] == "祖父"
    assert jg[0]["judge_resolves_to"] == "祖父"
    assert ad[0]["admission"] == "accept"
    assert rg[0]["registered"] is True and rg[0]["alias_to"] == "祖父"


def test_lineage_bare_role_observation_then_confirmed(ws_tmp):
    r = EntityResolver(judge=judge_resolves({"父亲": "顺顺"}), lineage=enabled_recorder(ws_tmp))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    r.resolve(make_chunk(2, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    r.resolve(make_chunk(3, text="顺顺父亲"), extraction(["父亲"], {"父亲": D}))
    evs = events_of(r._lineage)
    ad = [e for e in evs if e["event"] == "admission" and e["mention"] == "父亲"]
    regs = [e for e in evs if e["event"] == "registration" and e["mention"] == "父亲"]
    assert ad[0]["admission"] == "observation" and ad[0]["evidence_count"] == 1
    assert ad[-1]["admission"] == "confirmed"
    assert regs[0]["registered"] is False
    assert regs[-1]["registered"] is True and regs[-1]["alias_to"] == "顺顺"


def test_lineage_deferred_then_unresolved(ws_tmp):
    """index 为空 → BODY DESCRIPTIVE 无候选 → deferred → chunk 末重召回仍无 → unresolved。"""
    r = EntityResolver(judge=judge_resolves({}), lineage=enabled_recorder(ws_tmp))
    r.resolve(make_chunk(1, text="zz"), extraction(["大儿子"], {"大儿子": D}))
    evs = events_of(r._lineage)
    ad = [e for e in evs if e["event"] == "admission" and e["mention"] == "大儿子"]
    regs = [e for e in evs if e["event"] == "registration" and e["mention"] == "大儿子"]
    assert ad[0]["admission"] == "deferred"
    assert ad[-1]["admission"] == "deferred_unresolved"
    assert regs[-1]["registered"] is False


def test_lineage_judge_exception_path(ws_tmp):
    def failing_judge(text, pending):
        raise RuntimeError("boom")
    r = EntityResolver(judge=failing_judge, lineage=enabled_recorder(ws_tmp))
    r.resolve(make_chunk(1, text="翠翠"), extraction(["翠翠"], {"翠翠": P}))
    r.resolve(make_chunk(2, text="翠翠祖父"),
              extraction(["祖父", "翠翠的祖父"], {"祖父": P, "翠翠的祖父": D}))
    evs = events_of(r._lineage)
    jg = [e for e in evs if e["event"] == "judge" and e["mention"] == "翠翠的祖父"]
    assert jg and jg[-1]["judge_error"] == "RuntimeError"
    ad = [e for e in evs if e["event"] == "admission" and e["mention"] == "翠翠的祖父"]
    assert ad[-1]["admission"] == "exception_unresolved"
    rg = [e for e in evs if e["event"] == "registration" and e["mention"] == "翠翠的祖父"]
    assert rg[-1]["registered"] is False


# ---------- config 默认关 ----------

def test_settings_lineage_defaults_off(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-test")
    monkeypatch.setenv("BAILIAN_URL", BAILIAN_URL)
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    s = Settings(_env_file=None)
    assert s.er_lineage is False
    assert s.er_lineage_raw_extraction is False
    assert s.er_lineage_dir == "lineage"
    rec = create_lineage_recorder(s, "n1", "j1")
    assert rec.enabled is False
    assert rec.raw_extraction is False


def test_settings_lineage_env_enabled(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-test")
    monkeypatch.setenv("BAILIAN_URL", BAILIAN_URL)
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("ER_LINEAGE", "1")
    monkeypatch.setenv("ER_LINEAGE_RAW_EXTRACTION", "1")
    s = Settings(_env_file=None)
    assert s.er_lineage is True
    assert s.er_lineage_raw_extraction is True
    rec = create_lineage_recorder(s, "n1", "j1")
    assert rec.enabled is True and rec.raw_extraction is True


# ---------- diagnose_lineage 离线归层（四历史案例合成数据） ----------

def _base_events(mention="翠翠的祖父", category="descriptive", hygiene=None,
                 candidates=("祖父",), role=("qualified", True, "翠翠", True, "祖父"),
                 resolves_to=None, admission="null_unresolved", reason="judge_null",
                 registered=False, alias_to=None, final=None):
    kind, has_de, anchor, anchor_known, headword = role
    events = [
        {"event": "chunk_start", "chunk_id": 11, "chapter_id": 10, "section_type": "body",
         "text_len": 120, "characters_count": 2, "relationships_count": 0},
        {"event": "mention_enter", "lineage_id": "L1", "chunk_id": 11, "chapter_id": 10,
         "section_type": "body", "mention": mention, "extracted": True,
         "extraction_category": category, "hygiene_category": hygiene,
         "extraction_roles": ["character"]},
        {"event": "recall", "lineage_id": "L1", "chunk_id": 11, "chapter_id": 10,
         "section_type": "body", "mention": mention, "role_kind": kind, "role_has_de": has_de,
         "role_anchor": anchor, "role_anchor_known": anchor_known, "role_headword": headword,
         "recall_source": "strong_extraction" if candidates else "none",
         "recall_candidates": list(candidates)},
        {"event": "judge", "lineage_id": "L1", "chunk_id": 11, "chapter_id": 10,
         "section_type": "body", "mention": mention, "judge_called": True,
         "judge_input_mentions_count": 2, "judge_input_candidates": list(candidates) or None,
         "judge_resolves_to": resolves_to, "judge_missing": False, "judge_error": None},
        {"event": "admission", "lineage_id": "L1", "chunk_id": 11, "chapter_id": 10,
         "section_type": "body", "mention": mention, "admission": admission,
         "admission_reason": reason, "evidence_count": None,
         "role_confirmed": False, "role_blocked": False},
        {"event": "registration", "lineage_id": "L1", "chunk_id": 11, "chapter_id": 10,
         "section_type": "body", "mention": mention, "registered": registered,
         "alias_to": alias_to, "final_canonical": final, "provisional": False},
        {"event": "job_end", "status": "completed", "failed_blocks": [], "stats": {}},
    ]
    return events


def test_lineage_llm_generic_judge_null_skipped(ws_tmp):
    """D5-b（B-1）：LLM generic（非词表，母亲 型）+ judge null → admission=skipped_generic + 输出剔除。"""
    def judge_null(text, pending):
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})
    r = EntityResolver(judge=judge_null, lineage=enabled_recorder(ws_tmp))
    r.resolve(make_chunk(1, text="顺顺"), extraction(["顺顺"], {"顺顺": P}))
    out, _ = r.resolve(make_chunk(2, text="顺顺母亲"),
                       extraction(["母亲"], {"母亲": MentionCategory.GENERIC}))
    evs = events_of(r._lineage)
    ad = [e for e in evs if e["event"] == "admission" and e["mention"] == "母亲"]
    rg = [e for e in evs if e["event"] == "registration" and e["mention"] == "母亲"]
    assert ad and ad[-1]["admission"] == "skipped_generic" and ad[-1]["admission_reason"] == "generic_null"
    assert rg and rg[-1]["registered"] is False
    assert all(c.name != "母亲" for c in out.characters)


def test_diagnose_cuicui_grandfather_judge_null(ws_tmp):
    """翠翠的祖父：category=descriptive + 候选[祖父] + judge null → judge 层（P06）。"""
    p = write_jsonl(ws_tmp, _base_events(mention="翠翠的祖父", category="descriptive",
                                           candidates=("祖父",), resolves_to=None))
    verdict, _chain, notes = diagnose_mention(load_events(p), "翠翠的祖父", expect="祖父")
    assert verdict == "JUDGE_LAYER"
    assert any("judge 判 null" in n for n in notes)


def test_diagnose_cuicui_grandfather_success(ws_tmp):
    """翠翠的祖父：judge → 祖父 + accept + alias → SUCCESS。"""
    p = write_jsonl(ws_tmp, _base_events(mention="翠翠的祖父", category="descriptive",
                                           candidates=("祖父",), resolves_to="祖父",
                                           admission="accept", reason=None,
                                           registered=True, alias_to="祖父", final="祖父"))
    verdict, _, notes = diagnose_mention(load_events(p), "翠翠的祖父", expect="祖父")
    assert verdict == "SUCCESS"


def test_diagnose_yueyun_erlao_target_mismatch(ws_tmp):
    """岳云二老：composite + judge→傩送 + gate target_mismatch → admission 层。"""
    p = write_jsonl(ws_tmp, _base_events(
        mention="岳云二老", category="composite",
        candidates=("傩送",), role=("qualified", False, "岳云", True, "二老"),
        resolves_to="傩送", admission="reject", reason="target_mismatch"))
    verdict, _, notes = diagnose_mention(load_events(p), "岳云二老", expect="傩送")
    assert verdict == "ADMISSION_LAYER"
    assert any("target_mismatch" in n for n in notes)


def test_diagnose_didi_generic_judge_null(ws_tmp):
    """弟弟：hygiene=GENERIC（RC3）+ 候选[二老] + judge null → judge 层。"""
    p = write_jsonl(ws_tmp, _base_events(
        mention="弟弟", category=None, hygiene="generic",
        candidates=("二老",), role=("bare", False, None, False, None),
        resolves_to=None, admission="skipped_generic", reason="generic_null"))
    verdict, _, _ = diagnose_mention(load_events(p), "弟弟", expect="二老")
    assert verdict == "JUDGE_LAYER"


def test_diagnose_yeye_category_none_d5(ws_tmp):
    """爷爷：category=None + 无候选 → 注册自身 canonical（D5 绕过 gate）。"""
    p = write_jsonl(ws_tmp, _base_events(
        mention="爷爷", category=None, hygiene=None, candidates=(), resolves_to=None,
        admission="accept", reason="register_canonical", registered=True,
        alias_to=None, final="爷爷"))
    verdict, _, notes = diagnose_mention(load_events(p), "爷爷", expect="祖父")
    assert verdict == "CATEGORY_LAYER_D5"


def test_diagnose_merge_absorbed(ws_tmp):
    """alias 已建立但 canonical 被 merge_map 吸收（C_drop）→ merge 层。"""
    events = _base_events(mention="岳云二老", category="composite",
                          candidates=("二老",), role=("qualified", False, "岳云", True, "二老"),
                          resolves_to="二老", admission="accept", reason=None,
                          registered=True, alias_to="二老", final="二老")
    events.append({"event": "merge_drop", "canonical": "二老", "merge_keep": "傩送"})
    p = write_jsonl(ws_tmp, events)
    verdict, _, notes = diagnose_mention(load_events(p), "岳云二老", expect="傩送")
    assert verdict == "MERGE_LAYER"


def test_diagnose_not_extracted(ws_tmp):
    """无任何事件 + 无 failed chunk → extraction 层（未提取）。"""
    p = write_jsonl(ws_tmp, [
        {"event": "chunk_start", "chunk_id": 11, "chapter_id": 10, "section_type": "body",
         "text_len": 120, "characters_count": 2, "relationships_count": 0},
        {"event": "job_end", "status": "completed", "failed_blocks": [], "stats": {}},
    ])
    verdict, _, _ = diagnose_mention(load_events(p), "翠翠的祖父", expect="祖父")
    assert verdict == "EXTRACTION_LAYER"


def test_diagnose_expect_variant_alias_success(ws_tmp):
    """期望 二老，实际 alias 傩送 且 canonical_snapshot 中 二老 ∈ 傩送.aliases → SUCCESS（变体）。"""
    events = _base_events(mention="弟弟", category=None, hygiene="generic",
                          candidates=("傩送",), role=("bare", False, None, False, None),
                          resolves_to="傩送", admission="accept", reason=None,
                          registered=True, alias_to="傩送", final="傩送")
    events.append({"event": "canonical_snapshot", "canonicals": [
        {"canonical": "傩送", "aliases": ["二老", "傩送二老", "弟弟"],
         "mention_count": 15, "chapters": [5, 6]},
    ]})
    p = write_jsonl(ws_tmp, events)
    verdict, _, notes = diagnose_mention(load_events(p), "弟弟", expect="二老")
    assert verdict == "SUCCESS"
    assert any("别名变体" in n for n in notes)


def test_diagnose_failed_chunk_chain_break(ws_tmp):
    """mention 无事件 + job 有失败块 → 链路断点（失败 chunk / 未提取并存）。"""
    p = write_jsonl(ws_tmp, [
        {"event": "job_end", "status": "completed_with_errors",
         "failed_blocks": [{"chunk_id": 17, "chapter_id": 15, "error": "ReadTimeout"}], "stats": {}},
    ])
    verdict, chain, _ = diagnose_mention(load_events(p), "弟弟", expect="二老")
    assert verdict == "CHAIN_BREAK"
    assert any("17" in n for n in chain)
