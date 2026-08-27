"""V0.2.7 Task A：P06 lineage 观测 recorder（纯 observability，默认关闭）。

设计约束（Task A 评审锁定 2026-08-27）：
1. **lineage_id**：同一次 mention 处理实例（一个 chunk 内一个 mention）生成稳定 lineage_id，
   不同 pipeline 层（extraction / recall / judge / admission / registration）的事件都携带
   该 id，读取方可显式 join——不依赖 (chunk_id, mention) 隐式关联。
2. **默认关闭**：ER_LINEAGE 未设置时 recorder 为 no-op（所有方法空返回，零分配、零 IO）；
   判定路径逐字节不变（观测是旁路 tap，不是拦截）。
3. **extraction_raw 不作为默认 lineage 数据**：原始 extraction 三元组是可选 debug 能力，
   ER_LINEAGE_RAW_EXTRACTION=0 默认关闭；深挖 extraction 时再显式开启。
4. **不参与运行时业务逻辑**：本模块不 import resolver/merger，只记录已发生的决策结果。
5. **确定性落盘**：事件先收集于内存 list，job 终态一次性 flush 为
   <ER_LINEAGE_DIR>/<novel_id>.jsonl；失败 job 的 except 分支同样 flush。

事件类型（JSONL 一行 = 一个事件）：
- chunk_start          非 mention 级：chunk 对齐（text_len / 计数）
- mention_enter        ① extraction 层：mention 是否出现在 extraction 输出、category、roles
- recall               ② recall / role 判定层：role_kind/anchor/headword、recall_source、candidates
- judge                ③ judge 层：是否调用、resolves_to、missing / error
- admission            ④ admission 层：accept/reject/observation/confirmed/blocked/… + reason
- registration         ⑤ 注册/alias 层：registered / alias_to / final_canonical / provisional
- judge_batch          辅助：本 chunk judge 批次 mention 列表（P06 重放上下文）
- extraction_raw       辅助（ER_LINEAGE_RAW_EXTRACTION=1 时）：原始 characters/relationships 三元组
- merge_stats          辅助：merge 决策统计（candidate/merged/rejected/low_confidence/failed）
- merge_drop           ⑥ merge 层（canonical 级）：C_drop -> C_keep（merge_map 逐条）
- canonical_snapshot   辅助：job 末图内最终 canonical 状态（merge + finalize 后）
- job_end              辅助：job 终态 + failed_blocks + stats

字段约定：缺失值一律 null；MentionCategory 等枚举记 .value 字符串。
"""
import json
import uuid
from pathlib import Path

from app.config import Settings


def new_lineage_id() -> str:
    """每次 mention 处理实例的稳定 lineage_id（hex uuid，紧凑、确定性排序友好）。"""
    return uuid.uuid4().hex


class LineageRecorder:
    """内存收集 + job 终态一次性落盘。enabled=False 时所有方法为 no-op。"""

    def __init__(self, enabled: bool, novel_id: str = "", job_id: str = "",
                 raw_extraction: bool = False, out_dir: str = "lineage"):
        self.enabled = bool(enabled)
        self.novel_id = novel_id
        self.job_id = job_id
        self.raw_extraction = bool(raw_extraction)
        self.out_dir = out_dir
        self._events: list[dict] = []
        self._flushed = False

    # ---- 内部 ----

    def _base(self, event_type: str) -> dict:
        return {"event": event_type, "novel_id": self.novel_id, "job_id": self.job_id}

    def _emit(self, event: dict) -> None:
        if not self.enabled:
            return
        self._events.append(event)

    def _mention_base(self, event_type: str, *, lineage_id: str, chunk_id: int,
                      chapter_id: int, section_type: str, mention: str) -> dict:
        ev = self._base(event_type)
        ev.update({
            "lineage_id": lineage_id,
            "chunk_id": chunk_id,
            "chapter_id": chapter_id,
            "section_type": section_type,
            "mention": mention,
        })
        return ev

    # ---- ① extraction 层 ----

    def mention_enter(self, *, lineage_id: str, chunk_id: int, chapter_id: int,
                      section_type: str, mention: str, extracted: bool,
                      extraction_category: str | None, hygiene_category: str | None,
                      extraction_roles: list[str]) -> None:
        ev = self._mention_base("mention_enter", lineage_id=lineage_id, chunk_id=chunk_id,
                                chapter_id=chapter_id, section_type=section_type, mention=mention)
        ev.update({
            "extracted": bool(extracted),
            "extraction_category": extraction_category,
            "hygiene_category": hygiene_category,
            "extraction_roles": list(extraction_roles),
        })
        self._emit(ev)

    # ---- ② recall / role 判定层 ----

    def recall(self, *, lineage_id: str, chunk_id: int, chapter_id: int,
               section_type: str, mention: str, role_kind: str | None,
               role_has_de: bool | None, role_anchor: str | None,
               role_anchor_known: bool | None, role_headword: str | None,
               recall_source: str, recall_candidates: list[str]) -> None:
        ev = self._mention_base("recall", lineage_id=lineage_id, chunk_id=chunk_id,
                                chapter_id=chapter_id, section_type=section_type, mention=mention)
        ev.update({
            "role_kind": role_kind,
            "role_has_de": role_has_de,
            "role_anchor": role_anchor,
            "role_anchor_known": role_anchor_known,
            "role_headword": role_headword,
            "recall_source": recall_source,
            "recall_candidates": list(recall_candidates),
        })
        self._emit(ev)

    # ---- ③ judge 层 ----

    def judge(self, *, lineage_id: str, chunk_id: int, chapter_id: int,
              section_type: str, mention: str, judge_called: bool,
              judge_input_mentions_count: int | None,
              judge_input_candidates: list[str] | None,
              judge_resolves_to: str | None,
              judge_missing: bool, judge_error: str | None) -> None:
        ev = self._mention_base("judge", lineage_id=lineage_id, chunk_id=chunk_id,
                                chapter_id=chapter_id, section_type=section_type, mention=mention)
        ev.update({
            "judge_called": bool(judge_called),
            "judge_input_mentions_count": judge_input_mentions_count,
            "judge_input_candidates": list(judge_input_candidates) if judge_input_candidates else None,
            "judge_resolves_to": judge_resolves_to,
            "judge_missing": bool(judge_missing),
            "judge_error": judge_error,
        })
        self._emit(ev)

    # ---- ④ admission 层 ----

    def admission(self, *, lineage_id: str, chunk_id: int, chapter_id: int,
                  section_type: str, mention: str, admission: str,
                  admission_reason: str | None, evidence_count: int | None,
                  role_confirmed: bool, role_blocked: bool) -> None:
        ev = self._mention_base("admission", lineage_id=lineage_id, chunk_id=chunk_id,
                                chapter_id=chapter_id, section_type=section_type, mention=mention)
        ev.update({
            "admission": admission,
            "admission_reason": admission_reason,
            "evidence_count": evidence_count,
            "role_confirmed": bool(role_confirmed),
            "role_blocked": bool(role_blocked),
        })
        self._emit(ev)

    # ---- ⑤ registration 层 ----

    def registration(self, *, lineage_id: str, chunk_id: int, chapter_id: int,
                     section_type: str, mention: str, registered: bool,
                     alias_to: str | None, final_canonical: str | None,
                     provisional: bool) -> None:
        ev = self._mention_base("registration", lineage_id=lineage_id, chunk_id=chunk_id,
                                chapter_id=chapter_id, section_type=section_type, mention=mention)
        ev.update({
            "registered": bool(registered),
            "alias_to": alias_to,
            "final_canonical": final_canonical,
            "provisional": bool(provisional),
        })
        self._emit(ev)

    # ---- 辅助事件 ----

    def chunk_start(self, *, chunk_id: int, chapter_id: int, section_type: str,
                    text_len: int, characters_count: int, relationships_count: int) -> None:
        ev = self._base("chunk_start")
        ev.update({
            "chunk_id": chunk_id,
            "chapter_id": chapter_id,
            "section_type": section_type,
            "text_len": text_len,
            "characters_count": characters_count,
            "relationships_count": relationships_count,
        })
        self._emit(ev)

    def judge_batch(self, *, chunk_id: int, chapter_id: int, mentions: list[str]) -> None:
        ev = self._base("judge_batch")
        ev.update({"chunk_id": chunk_id, "chapter_id": chapter_id,
                   "mentions": list(mentions)})
        self._emit(ev)

    def extraction_raw(self, *, chunk_id: int, chapter_id: int,
                       characters: list[dict], relationships: list[dict]) -> None:
        if not self.raw_extraction:
            return
        ev = self._base("extraction_raw")
        ev.update({"chunk_id": chunk_id, "chapter_id": chapter_id,
                   "characters": characters, "relationships": relationships})
        self._emit(ev)

    def merge_stats(self, *, stats: dict) -> None:
        ev = self._base("merge_stats")
        ev.update({"stats": dict(stats)})
        self._emit(ev)

    def merge_drop(self, *, canonical: str, merge_keep: str) -> None:
        ev = self._base("merge_drop")
        ev.update({"canonical": canonical, "merge_keep": merge_keep})
        self._emit(ev)

    def canonical_snapshot(self, *, canonicals: list[dict]) -> None:
        ev = self._base("canonical_snapshot")
        ev.update({"canonicals": list(canonicals)})
        self._emit(ev)

    def job_end(self, *, status: str, failed_blocks: list[dict], stats: dict | None) -> None:
        ev = self._base("job_end")
        ev.update({"status": status, "failed_blocks": list(failed_blocks), "stats": stats})
        self._emit(ev)

    # ---- 落盘 ----

    def flush(self, path: str | Path | None = None) -> Path | None:
        """一次性写 JSONL（每行一个事件）。失败 job 的 except 分支同样调用。

        幂等：已 flush 后再次调用为 no-op。写失败不抛异常（不掩盖 job 状态更新）。
        """
        if not self.enabled or self._flushed:
            return None
        out = Path(path) if path is not None else Path(self.out_dir) / f"{self.novel_id}.jsonl"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                for ev in self._events:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self._flushed = True
            return out
        except OSError:
            return None

    def __len__(self) -> int:
        return len(self._events)


def create_lineage_recorder(settings: Settings, novel_id: str, job_id: str) -> LineageRecorder:
    """按 settings 构建 recorder：ER_LINEAGE=1 启用；未设置时为 no-op（零行为）。"""
    return LineageRecorder(
        enabled=settings.er_lineage,
        novel_id=novel_id,
        job_id=job_id,
        raw_extraction=settings.er_lineage_raw_extraction,
        out_dir=settings.er_lineage_dir,
    )
