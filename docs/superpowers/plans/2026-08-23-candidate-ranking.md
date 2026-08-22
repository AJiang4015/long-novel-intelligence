# V0.2.3-a Candidate Ranking 修正（强信号永不挤掉）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 `_recall` 为 strong/weak 两段式候选容量，保证 strong（extraction + text confirmed）永不因 weak Top-K 截断，`天保大老` 候选必含 `天保` 与 `大老`。

**Architecture:** `_recall` 中 strong 层（extraction confirmed → text confirmed，canonical 去重）全部保留、不受 `RECALL_TOP_K` 限制；weak 层（字符重合/子串）只补足剩余容量。`RECALL_TOP_K` 语义从「最终硬上限」改为「weak 补位目标容量」，值仍为 5。weak 排序增加确定性 tie-break（canonical 字符串升序），不依赖 set/dict 隐式顺序。

**Tech Stack:** Python 3.x + pydantic（现有），无新依赖。

## Global Constraints

- 只改 `backend/app/pipeline/resolver.py` 与 `backend/tests/unit/test_resolver.py`
- 不改 judge / canonical merge / extraction / Neo4j / API / frontend（业务范围不变）
- 不重新导入《边城》，不调用真实 LLM 做验收（pytest 全 mock）
- `RECALL_TOP_K = 5` 常量值不变，仅语义改为「weak 补位目标容量」
- strong 内部顺序保持：extraction confirmed 在前，text confirmed 在后
- 最终公式：`final = strong + weak[:max(0, RECALL_TOP_K - len(strong))]`
- 确定性 tie-break：weak 排序键 `(-prio, -overlap, canonical字符串升序)`，不得依赖 set/dict 迭代序
- 测试命令统一 `cd backend && python -m pytest ...`（conftest 注入 `backend/.deps`）

---

### Task 1: 新增 4 个候选容量测试（红）

**Files:**
- Modify: `backend/tests/unit/test_resolver.py`（文件末尾追加）
- Test: `backend/tests/unit/test_resolver.py`

**Interfaces:**
- Consumes: `EntityResolver`、`make_chunk`、`extraction`、`_recorder`（已存在于 test_resolver.py）
- Produces: `test_strong_3_weak_fills_to_5`、`test_strong_5_no_weak`、`test_strong_7_not_truncated`、`test_bridge_mention_keeps_text_signal_when_extraction_full`

- [ ] **Step 1: 在 `backend/tests/unit/test_resolver.py` 末尾追加以下测试**

在文件最后一行（`test_text_candidates_priority_and_topk_merge` 的断言之后）追加：

```python


# ═══════════ V0.2.3-a strong/weak 候选容量（强信号永不挤掉）═══════════

def test_strong_3_weak_fills_to_5():
    """strong=3（extraction 2 + text 1）→ weak 补 2 个，最终 5。"""
    seen: dict = {}
    r = EntityResolver(judge=_recorder(seen))
    r.resolve(make_chunk(1, "A"),
              extraction(["傩送", "大老", "天保", "老人", "老船夫", "老马兵", "老道士"]))
    seen.clear()
    # 提取 傩送/大老（extraction confirmed=2）；原文含 天保（text confirmed=1）→ strong=3
    r.resolve(make_chunk(2, text="天保在河边"), extraction(["傩送", "大老", "二老"]))
    cands = seen["cands"][0]
    assert set(cands[:2]) == {"傩送", "大老"}   # extraction 层（顺序不定，集合断言）
    assert cands[2] == "天保"                    # text 层紧随其后
    assert len(cands) == 5                       # weak 补 2 个
    assert len(set(cands)) == len(cands)         # 无重复


def test_strong_5_no_weak():
    """strong=5 → weak 不补，最终 5。"""
    seen: dict = {}
    r = EntityResolver(judge=_recorder(seen))
    r.resolve(make_chunk(1, "A"),
              extraction(["傩送", "大老", "天保", "老人", "老船夫"]))
    seen.clear()
    # 提取 5 个已知 → extraction confirmed=5 → strong=5，weak 无剩余容量
    r.resolve(make_chunk(2, text="一个完全不同的段落"),
              extraction(["傩送", "大老", "天保", "老人", "老船夫", "二老"]))
    cands = seen["cands"][0]
    assert len(cands) == 5
    assert set(cands) == {"傩送", "大老", "天保", "老人", "老船夫"}


def test_strong_7_not_truncated():
    """strong=7 → 7 个全部保留，不截断（旧行为 `out[:5]` 会截到 5）。"""
    seen: dict = {}
    r = EntityResolver(judge=_recorder(seen))
    seed7 = ["傩送", "大老", "天保", "老人", "老船夫", "老马兵", "老道士"]
    r.resolve(make_chunk(1, "A"), extraction(seed7))
    seen.clear()
    r.resolve(make_chunk(2, text="一个完全不同的段落"), extraction(seed7 + ["二老"]))
    cands = seen["cands"][0]
    assert len(cands) == 7
    assert set(cands) == set(seed7)


def test_bridge_mention_keeps_text_signal_when_extraction_full():
    """V0.2.3-a 目标场景：extraction confirmed 已满 5 时，
    text confirmed 的 天保 仍进入候选（天保大老 候选必含 天保 与 大老）。"""
    seen: dict = {}
    r = EntityResolver(judge=_recorder(seen))
    r.resolve(make_chunk(1, "A"),
              extraction(["大老", "老人", "老船夫", "老马兵", "老道士", "天保"]))
    seen.clear()
    # 提取 5 个已知（无 天保）→ extraction confirmed=5 占满；原文含 天保 → text confirmed=天保
    r.resolve(make_chunk(2, text="天保大老在河边"),
              extraction(["大老", "老人", "老船夫", "老马兵", "老道士", "天保大老"]))
    cands = seen["cands"][0]
    assert "天保" in cands          # text 强信号未被 extraction 占满挤掉
    assert "大老" in cands          # extraction 强信号在
    assert len(cands) == 6          # strong=6（5 extraction + 1 text），weak=0
```

- [ ] **Step 2: 运行新测试确认失败（红）**

Run: `cd backend && python -m pytest tests/unit/test_resolver.py -k "strong or bridge" -v`

Expected: `test_strong_7_not_truncated` FAIL（旧代码 `out[:5]` 截到 5）、`test_bridge_mention_keeps_text_signal_when_extraction_full` FAIL（`天保` 第 6 位被截）、`test_strong_3_weak_fills_to_5` 与 `test_strong_5_no_weak` PASS（旧代码下不区分，仍通过）。

- [ ] **Step 3: Commit（测试先行，红状态可提交）**

```bash
git add backend/tests/unit/test_resolver.py
git commit -m "test: V0.2.3-a strong/weak 候选容量测试（3 容量 + bridge 目标场景）"
```

---

### Task 2: 实现 `_recall` 两段式 + 确定性 tie-break（绿）

**Files:**
- Modify: `backend/app/pipeline/resolver.py:114-164`（`_recall` 方法整体替换）

**Interfaces:**
- Consumes: `RECALL_TOP_K`（L7，值不变）、`_overlap`（L14）、`AliasCandidate`、`self._index`
- Produces: `_recall(mention, confirmed, text_confirmed) -> list[AliasCandidate]`，签名不变；`final = strong + weak[:max(0, RECALL_TOP_K - len(strong))]`；weak 排序键 `(-prio, -overlap, canonical)`

- [ ] **Step 1: 替换 `_recall` 实现**

将 `resolver.py` L114-164 的整个 `_recall` 方法替换为：

```python
    def _recall(self, mention: str, confirmed: set[str], text_confirmed: set[str]) -> list[AliasCandidate]:
        """候选召回（V0.2.3-a strong/weak 两段式）：

        - strong（全部保留，不受 RECALL_TOP_K 限制）：
          ① extraction 共现（confirmed，本 chunk 提取输出中已确认的 canonical）
          ② 文本层共现（text_confirmed，chunk 原文出现的已知 canonical/alias）
          strong 按 canonical 去重，extraction 在前、text 在后。
        - weak（只补足到 RECALL_TOP_K）：字符重合/子串，确定性 tie-break。
        - RECALL_TOP_K 语义 = weak 补位目标容量，不再是最终候选数硬上限。
        """
        out: list[AliasCandidate] = []
        seen: set[str] = set()

        # 1) strong：extraction 共现候选（强，优先）
        for canonical in confirmed:
            if canonical == mention or canonical not in self._index or canonical in seen:
                continue
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))

        # 2) strong：文本层共现候选（强，顺序在 extraction 之后）
        for canonical in text_confirmed:
            if canonical == mention or canonical not in self._index or canonical in seen:
                continue
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))

        # 3) weak：字符重合 + 子串候选，只补足剩余容量；确定性 tie-break（不依赖 set/dict 顺序）
        scored: list[tuple[int, int, str]] = []
        for canonical, names in self._index.items():
            if canonical in seen:
                continue
            hit = None
            for n in names:
                if mention in n or n in mention:      # 子串包含优先
                    hit = n
                    break
            overlap = max(_overlap(mention, n) for n in names) if names else 0
            scored.append((1 if hit else 0, overlap, canonical))
        # 排序键：-prio（子串命中优先）、-overlap（共享字符多优先）、canonical 升序（确定性 tie-break）
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        for _prio, _ov, canonical in scored[: max(0, RECALL_TOP_K - len(out))]:
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))
        return out
```

**要点**：
- 原 `return out[:RECALL_TOP_K]` 删除——strong 不再被总截断
- weak 的 `scored[: max(0, RECALL_TOP_K - len(out))]` 已保证只补位；`len(out)` 此时即 strong 数量
- 排序从 `(t[0], t[1]) reverse=True` 改为 `(-t[0], -t[1], t[2])` 升序——`t[2]` canonical 字符串提供确定性 tie-break，与插入序无关

- [ ] **Step 2: 运行新测试确认通过（绿）**

Run: `cd backend && python -m pytest tests/unit/test_resolver.py -k "strong or bridge" -v`

Expected: 4 个全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add backend/app/pipeline/resolver.py
git commit -m "feat(resolver): V0.2.3-a strong 永不挤掉，weak 只补位 + 确定性 tie-break"
```

---

### Task 3: resolver 全量回归（现有 19 个测试不破坏）

**Files:**
- Test: `backend/tests/unit/test_resolver.py`

**Interfaces:**
- Consumes: Task 2 的 `_recall` 新实现
- Produces: 无新接口；确认既有断言不受影响

- [ ] **Step 1: 运行 resolver 全量**

Run: `cd backend && python -m pytest tests/unit/test_resolver.py -v`

Expected: 全部 PASS（现 19 + 新 4 = 23）。重点确认：
- `test_text_no_known_names_no_text_candidates` 仍断言 `cands[0][0] == "大老"`（确定性 tie-break 下 大老 仍在弱候选首位，已预验证）
- `test_cooccurrence_candidate_priority_over_char_overlap` 仍断言 `[["傩送", "大老"]]`（strong=1 + weak=1，不受影响）
- `test_text_candidates_priority_and_topk_merge` 仍断言 `cands[:2] == ["傩送", "天保"]`（strong=2，weak 补 3 ≤5）

- [ ] **Step 2: 若任一失败，检查失败断言是否与新的 strong/weak 语义冲突**

如 `test_text_no_known_names_no_text_candidates` 失败：确认 weak 排序 key 是 `(-t[0], -t[1], t[2])` 且 `大老`（U+5927 开头）在字符串升序中最小——已预验证通过，不应失败。

- [ ] **Step 3: Commit（如无失败，跳过本步；如修了代码，提交）**

```bash
git status
```

---

### Task 4: unit 全量

**Files:**
- Test: `backend/tests/unit/`

- [ ] **Step 1: 运行 unit 全量**

Run: `cd backend && python -m pytest`

Expected: 全部 PASS（test_config / test_chunker / test_merger / test_llm_client / test_job_store / test_resolver）。

- [ ] **Step 2: 无代码改动则无 commit；有改动则提交**

---

### Task 5: integration 全量

**Files:**
- Test: `backend/tests/integration/`

- [ ] **Step 1: 确认 novel-neo4j 运行中**

Run: `docker ps --filter name=neo4j`（或 SSH `centos101` 上 `docker ps`），确认 novel-neo4j 容器 UP。若未运行，先启动（不属本任务范围，仅前置条件）。

- [ ] **Step 2: 运行 integration 全量**

Run: `cd backend && python -m pytest -m integration`

Expected: 全部 PASS（13 项；`db` fixture 连不上时 `pytest.skip`，不算失败）。注意：集成测试使用独立 novel_id 自建自清，不触碰真实数据。

- [ ] **Step 3: 无代码改动则无 commit**

---

### Task 6: deterministic candidate probe（不调真实 LLM）

**Files:**
- Create: `.tmp/probe_candidate_ranking.py`（工作区临时文件，不提交）

**Interfaces:**
- Consumes: `EntityResolver`、`LLMClient`（不使用——全 mock judge）
- Produces: stdout 输出确定性候选列表（验证 `天保大老` 场景）

- [ ] **Step 1: 写 probe 脚本**

```python
"""V0.2.3-a 确定性候选探测：验证 天保大老 → 候选必含 天保 与 大老（不调用真实 LLM）。"""
import sys
sys.path.insert(0, r"E:\CodeField\Long-Novel-Intelligence\backend")
from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import AliasJudgeResult, ExtractionResult


def make_chunk(chunk_id, text="文本"):
    return Chunk(chunk_id=chunk_id, chapter_id=1, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(names):
    return ExtractionResult.model_validate(
        {"characters": [{"name": n} for n in names], "relationships": []})


def recorder(text, pending):
    # 记录候选，不做任何判定（全部 None → 独立 canonical）
    print("PENDING:", [(p.mention, [c.canonical for c in p.candidates]) for p in pending])
    return AliasJudgeResult.model_validate(
        {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})


r = EntityResolver(judge=recorder)
# chunk1：确立 大老/老人/老船夫/老马兵/老道士/天保 为 canonical
r.resolve(make_chunk(1, "A"),
          extraction(["大老", "老人", "老船夫", "老马兵", "老道士", "天保"]))
print("=== chunk2: 提取 5 个已知 + 天保大老，原文含 天保大老 ===")
r.resolve(make_chunk(2, text="天保大老在河边"),
          extraction(["大老", "老人", "老船夫", "老马兵", "老道士", "天保大老"]))
```

- [ ] **Step 2: 运行 probe**

Run: `cd backend && $env:PYTHONPATH="backend\.deps;backend"; python -u .tmp\probe_candidate_ranking.py`

Expected stdout（确定性）：
```
PENDING: [('天保大老', ['大老', '老人', '老船夫', '老马兵', '老道士', '天保'])]
```
（strong 6 个：extraction 5 个 + text 1 个 `天保`；`天保` 在末位——extraction 层 set 迭代序不定，但 `天保` 一定在列表内且 `大老` 一定在列表内）

- [ ] **Step 3: 断言核对**

`天保大老` 的候选包含 `天保` 与 `大老` → 目标达成。若 `天保` 不在候选，说明 Task 2 实现有误，回到 Task 2 排查。

- [ ] **Step 4: 不提交 `.tmp/`（gitignore 已覆盖或直接删除）**

```bash
Remove-Item .tmp/probe_candidate_ranking.py
```

---

## Self-Review

**1. Spec 覆盖：**
- 背景/问题（chunk 11 天保被截断）→ Task 1 bridge 测试 + Task 2 实现 ✓
- 目标（天保大老 → 候选含 天保、大老）→ Task 1 `test_bridge_mention_keeps_text_signal_when_extraction_full` + Task 6 probe ✓
- 强信号无上限、weak 只补位 → Task 2 公式 `final = strong + weak[:max(0, RECALL_TOP_K - len(strong))]` ✓
- strong 内部顺序 extraction → text → Task 2 循环顺序 ✓
- canonical 级去重 → Task 2 `seen` 集合 ✓
- RECALL_TOP_K 语义变更（值不变）→ Task 2 docstring + Global Constraints ✓
- 确定性 tie-break（用户约束 2）→ Task 2 排序键 `(-t[0], -t[1], t[2])` ✓
- 验证顺序（3 容量 → resolver → unit → integration → probe）→ Task 1→3→4→5→6 ✓
- 不改 judge/merge/extraction/Neo4j/API/frontend → 只改 resolver.py + test_resolver.py（+ .tmp 临时脚本）✓

**2. Placeholder 扫描：** 无 TBD/TODO；每步含完整代码与命令。

**3. 类型一致性：** `_recall` 签名不变（`mention: str, confirmed: set[str], text_confirmed: set[str]) -> list[AliasCandidate]`）；测试用现有 `_recorder`/`make_chunk`/`extraction` helpers；`seen["cands"][0]` 取第一个 pending mention 的候选，与现有测试模式一致。
