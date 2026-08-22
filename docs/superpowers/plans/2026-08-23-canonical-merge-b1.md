# V0.2.3-b1 Canonical Merge Decision 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 b1 纯 decision：bridge evidence → canonical pair 去重 → batch merge judge → `merge_map`。不写 Neo4j、不改 PersonAgg/upsert_graph、不实现 b2。

**Architecture:** resolver 在 resolve() 过程中旁路收集 merge_evidence（mention 候选含 ≥2 established canonical 时）；resolve 结束后 `decide_merges()` 基于 **canonical metadata 快照**（resolve 完成时的 known/_index/canonical_aliases + first_seen/mention_count/chapters 统计）构建 pair、调用独立 merge judge（新契约）、过滤（threshold 可配置）、产出 `merge_map`。b1 全程不修改 known/_index/canonical_aliases，不提前应用 merge_map，不做传递合并。

**Tech Stack:** Python 3.x + pydantic（现有），无新依赖。

## Global Constraints

- 只实现 b1：bridge evidence → pair → merge judge → merge_map；**不实现 b2**
- **b1 纯 decision（强制）**：不修改 `known` / `_index` / `canonical_aliases`；不改写任何 chunk 的 resolved 输出
- **snapshot 独立判定（强制）**：所有 pair 输入来自同一份 resolve 完成后的 canonical metadata 快照；A↔B、B↔C 各自独立判定；**不得提前应用 merge_map、不得隐式传递合并**（A≈B、B≈C 不推导 A≈C）
- 不修改 Neo4j / PersonAgg / `upsert_graph` / 前端 / GraphResponse / API
- 不调用真实 LLM（测试全 mock merge judge）
- `merge_confidence_threshold` 可配置（构造参数注入），不硬编码 0.5
- judge failure → 不 merge；confidence < threshold → 不 merge；统计入 `stats.entity_resolution`，**不污染 failed_blocks**
- merge judge 失败详情可选进 `merge_failures`
- C_keep = first_seen_chunk 更小者；相同 → 确定性 tie-break（(first_seen, canonical 字符串) 元组升序）
- 测试命令统一 `cd backend && python -m pytest ...`

---

### Task 1: merge 契约 schema（schemas/llm.py）

**Files:**
- Modify: `backend/app/schemas/llm.py`（文件末尾追加）

**Interfaces:**
- Consumes: 无（纯新契约）
- Produces: `MergePairSide`、`BridgeEvidence`、`MergePair`、`MergeDecision`、`MergeJudgeResult`（供 Task 3/4 使用）

- [ ] **Step 1: 在 `backend/app/schemas/llm.py` 末尾追加契约**

```python
# ---- V0.2.3-b1 canonical merge 契约（独立于 alias judge）----


class MergePairSide(BaseModel):
    canonical: str = Field(min_length=1, max_length=50)
    aliases: list[str] = Field(default_factory=list)
    first_seen_chunk: int = Field(ge=0)
    mention_count: int = Field(ge=0)
    chapters: list[int] = Field(default_factory=list)


class BridgeEvidence(BaseModel):
    chunk_id: int = Field(ge=0)
    chapter_id: int = Field(ge=0)
    mention: str = Field(min_length=1, max_length=50)
    text: str = Field(default="")


class MergePair(BaseModel):
    a: MergePairSide
    b: MergePairSide
    bridge_evidence: list[BridgeEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def a_neq_b(self):
        if self.a.canonical == self.b.canonical:
            raise ValueError("merge pair 两侧 canonical 不得相同")
        return self


class MergeDecision(BaseModel):
    a: str = Field(min_length=1, max_length=50)
    b: str = Field(min_length=1, max_length=50)
    merge: bool
    confidence: float = Field(ge=0.0, le=1.0)


class MergeJudgeResult(BaseModel):
    merges: list[MergeDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def dedupe_pairs(self):
        seen: set[frozenset] = set()
        kept: list[MergeDecision] = []
        for m in self.merges:
            key = frozenset((m.a, m.b))
            if key not in seen:
                seen.add(key)
                kept.append(m)
        self.merges = kept
        return self
```

- [ ] **Step 2: 验证 schema 可导入且约束生效**

Run: `cd backend && python -c "from app.schemas.llm import MergePair, MergeJudgeResult; import json; print(MergePair.model_validate_json('{\"a\":{\"canonical\":\"X\",\"first_seen_chunk\":1},\"b\":{\"canonical\":\"Y\",\"first_seen_chunk\":2}}').a.canonical); print(MergeJudgeResult.model_validate_json('{\"merges\":[{\"a\":\"X\",\"b\":\"Y\",\"merge\":true,\"confidence\":0.9},{\"a\":\"Y\",\"b\":\"X\",\"merge\":true,\"confidence\":0.8}]}').merges)"`

Expected: 输出 `X` 与 1 条 merges（(X,Y) 与 (Y,X) 去重为一条）。

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/llm.py
git commit -m "feat(schemas): V0.2.3-b1 merge 契约（MergePair/MergeDecision/MergeJudgeResult）"
```

---

### Task 2: b1 测试（红）

**Files:**
- Create: `backend/tests/unit/test_merge.py`

**Interfaces:**
- Consumes: `EntityResolver`（resolve + 新增 decide_merges/resolve_merge_root/merge_map/merge_evidence）、`make_chunk`/`extraction` 模式（从 test_resolver.py 复制 helper）
- Produces: 11 个 b1 测试（§3.8 设计文档）

- [ ] **Step 1: 创建 `backend/tests/unit/test_merge.py`**

```python
"""V0.2.3-b1 canonical merge decision 测试（mock merge judge，不调真实 LLM）。"""
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MergeJudgeResult


def make_chunk(chunk_id, chapter_id=1, text="文本"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(names, rels=None):
    return ExtractionResult.model_validate({
        "characters": [{"name": n} for n in names],
        "relationships": rels or [],
    })


def judge_null(text, pending):
    return AliasJudgeResult.model_validate(
        {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})


class _AliasJudge:
    """mock alias judge：mapping = {mention -> canonical | None}。"""

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def __call__(self, text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [
                {"mention": p.mention, "resolves_to": self.mapping.get(p.mention)}
                for p in pending
            ],
        })


class _MergeJudge:
    """mock merge judge：mapping = {(a,b) frozenset -> bool}；可配置失败。"""

    def __init__(self, mapping=None, failure=None, confidence=0.9):
        self.mapping = mapping or {}
        self.failure = failure  # 抛出的异常，模拟 judge 失败
        self.confidence = confidence
        self.calls = 0
        self.last_input = None

    def __call__(self, pairs):
        self.calls += 1
        self.last_input = pairs
        if self.failure is not None:
            raise self.failure
        merges = []
        for p in pairs:
            key = frozenset((p.a.canonical, p.b.canonical))
            merge = self.mapping.get(key, False)
            merges.append({"a": p.a.canonical, "b": p.b.canonical,
                           "merge": merge, "confidence": self.confidence})
        return MergeJudgeResult.model_validate({"merges": merges})


def build_two_canonicals(r, chunk_ids, names):
    """依次 resolve 若干 chunk 确立 canonical；返回 established 快照后的 resolver。"""
    for cid, name in zip(chunk_ids, names):
        r.resolve(make_chunk(cid, text=f"{name}在河边"), extraction([name]))
    return r


# 1. A/B 同人 → merge_map 产生 merge
def test_same_person_merges():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [6, 9], ["大儿子", "大老"])
    judge = _MergeJudge(mapping={frozenset(("大儿子", "大老")): True})
    # 手动注入 bridge evidence（chunk 11 mention 天保大老）
    r.merge_evidence.append({
        "mention": "天保大老", "candidates": ["大儿子", "大老"],
        "pair": ["大儿子", "大老"], "chunk_id": 11, "chapter_id": 3,
        "text": "天保大老过溪",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {"大老": "大儿子"}   # first_seen 6 < 9 → 大儿子 keep
    assert out["stats"]["entity_resolution"]["merged_pairs"] == 1


# 2. A/B 不同人 → 不 merge
def test_different_persons_not_merged():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["翠翠", "傩送"])
    judge = _MergeJudge(mapping={frozenset(("翠翠", "傩送")): False})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["翠翠", "傩送"],
        "pair": ["翠翠", "傩送"], "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {}
    assert out["stats"]["entity_resolution"]["rejected_pairs"] == 1


# 3. bridge mention 双侧命中 → 产生 pair（resolve 过程中自动收集）
def test_bridge_mention_generates_pair():
    # 模拟真实《边城》：chunk6 大儿子 成为 canonical，天保 并入大儿子（alias）
    r = EntityResolver(judge=_AliasJudge({"天保": "大儿子"}))
    r.resolve(make_chunk(6, text="他把长子取名天保"), extraction(["大儿子", "天保"]))
    r.resolve(make_chunk(9, text="大老在河边"), extraction(["大老"]))
    # chunk 11：提取 大老（known）+ 天保大老（未知）；原文含 天保（大儿子 的 alias）→ text confirmed 命中大儿子
    r.resolve(make_chunk(11, text="天保大老在河边"), extraction(["大老", "天保大老"]))
    assert len(r.merge_evidence) >= 1
    ev = r.merge_evidence[0]
    assert ev["mention"] == "天保大老"
    assert set(ev["pair"]) == {"大儿子", "大老"}
    assert ev["chunk_id"] == 11
    assert "text" in ev and ev["text"]


# 4. pair 去重（同 pair 只判一次）
def test_pair_dedup():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True})
    for i in range(3):
        r.merge_evidence.append({
            "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
            "chunk_id": 10 + i, "chapter_id": 1, "text": f"e{i}",
        })
    out = r.decide_merges(judge)
    assert judge.calls == 1            # 一次批量判定
    assert out["merge_map"] == {"B": "A"}
    assert len(judge.last_input) == 1  # pair 去重后只有 1 个输入


# 5. judge failure → 不 merge，不抛异常
def test_judge_failure_no_merge():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(failure=RuntimeError("http_429"))
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {}
    stats = out["stats"]["entity_resolution"]
    assert stats["failed_pairs"] == 1
    assert len(out["merge_failures"]) == 1


# 6. confidence 低于可配置阈值 → 不 merge
def test_low_confidence_not_merged():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True}, confidence=0.3)
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge, confidence_threshold=0.5)
    assert out["merge_map"] == {}
    assert out["stats"]["entity_resolution"]["rejected_pairs"] == 1


# 7. first_seen 更早者成为 keep
def test_first_seen_earlier_is_keep():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [9, 6], ["B", "A"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 11, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {"B": "A"}   # A first_seen 6 < B first_seen 9 → A keep


# 8. A/B 已通过 merge_map 合并 → 不重复生成 pair（同一 pair 幂等）
def test_existing_merge_not_duplicated():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    judge = _MergeJudge(mapping={frozenset(("A", "B")): True})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    r.decide_merges(judge)
    r.merge_evidence.append({
        "mention": "桥2", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 4, "chapter_id": 1, "text": "y",
    })
    out = r.decide_merges(judge)
    assert out["merge_map"] == {"B": "A"}   # 结果幂等


# 9. 不做全局 O(N²) comparison（构造 >100 canonical 仍线性/可用）
def test_many_canonicals_no_o2():
    r = EntityResolver(judge=judge_null)
    for i in range(1, 101):
        r.resolve(make_chunk(i, text=f"人物{i}在河边"), extraction([f"人物{i}"]))
    # 注入 1 个桥接 evidence → 只判 1 个 pair，不触发全量比较
    judge = _MergeJudge(mapping={frozenset(("人物1", "人物2")): True})
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["人物1", "人物2"], "pair": ["人物1", "人物2"],
        "chunk_id": 101, "chapter_id": 1, "text": "x",
    })
    out = r.decide_merges(judge)
    assert judge.calls == 1
    assert len(judge.last_input) == 1


# 10. b1 纯 decision 锁死：known/_index/canonical_aliases 快照不变
def test_b1_pure_decision_no_state_mutation():
    r = build_two_canonicals(EntityResolver(judge=judge_null), [1, 2], ["A", "B"])
    r.merge_evidence.append({
        "mention": "桥", "candidates": ["A", "B"], "pair": ["A", "B"],
        "chunk_id": 3, "chapter_id": 1, "text": "x",
    })
    before = (dict(r.known), {k: set(v) for k, v in r._index.items()},
              {k: list(v) for k, v in r.canonical_aliases.items()})
    r.decide_merges(_MergeJudge(mapping={frozenset(("A", "B")): True}))
    after = (dict(r.known), {k: set(v) for k, v in r._index.items()},
             {k: list(v) for k, v in r.canonical_aliases.items()})
    assert before == after


# 11. merge_evidence 完整结构 + 3 canonical 命中生成 3 条
def test_merge_evidence_structure_and_3way_pairs():
    # 三个 established canonical：A（含 alias a1）、B、C
    r = EntityResolver(judge=_AliasJudge({"a1": "A"}))
    r.resolve(make_chunk(1, text="A在河边"), extraction(["A", "a1"]))
    r.resolve(make_chunk(2, text="B在河边"), extraction(["B"]))
    r.resolve(make_chunk(3, text="C在河边"), extraction(["C"]))
    # chunk 4：提取 B/C（known）+ 桥（未知），原文含 a1（A 的 alias）→ text confirmed 命中 A
    # 桥 的候选同时含 A/B/C（established）→ 生成 3 条 pair evidence
    r.resolve(make_chunk(4, text="a1和B还有C都在河边"), extraction(["B", "C", "桥"]))
    pairs = {frozenset(ev["pair"]) for ev in r.merge_evidence}
    assert len(r.merge_evidence) == 3          # (A,B)(A,C)(B,C)
    assert frozenset(("A", "B")) in pairs
    assert frozenset(("A", "C")) in pairs
    assert frozenset(("B", "C")) in pairs
    ev = r.merge_evidence[0]
    assert set(ev) >= {"mention", "candidates", "pair", "chunk_id", "chapter_id", "text"}
    assert ev["chunk_id"] == 4
```

- [ ] **Step 2: 运行确认红**

Run: `cd backend && python -m pytest tests/unit/test_merge.py -v`

Expected: 收集错误（`AttributeError: 'EntityResolver' object has no attribute 'merge_evidence'`）或全部 FAIL——`decide_merges`/`merge_evidence` 尚未实现。

- [ ] **Step 3: Commit（红状态可提交）**

```bash
git add backend/tests/unit/test_merge.py
git commit -m "test: V0.2.3-b1 merge decision 测试（11 项，mock judge）"
```

---

### Task 3: resolver 实现（绿）

**Files:**
- Modify: `backend/app/pipeline/resolver.py`

**Interfaces:**
- Consumes: `MergePair`/`MergePairSide`/`BridgeEvidence`/`MergeJudgeResult`（Task 1）
- Produces:
  - `EntityResolver.merge_evidence: list[dict]`（resolve 中旁路收集）
  - `EntityResolver.merge_map: dict[str, str]`
  - `EntityResolver._first_seen: dict[str, int]`、`_canonical_chunks: dict[str, set[int]]`、`_canonical_chapters: dict[str, set[int]]`
  - `EntityResolver.decide_merges(merge_judge, confidence_threshold=0.5) -> dict`
  - `EntityResolver.resolve_merge_root(name) -> str`

- [ ] **Step 1: `__init__` 增加状态**

在 `__init__`（L21-25）中追加：

```python
        # ---- V0.2.3-b1：canonical metadata + merge decision（纯 decision，不改上述状态）----
        self.merge_evidence: list[dict] = []          # 桥接 mention 旁路证据
        self.merge_map: dict[str, str] = {}           # C_drop -> C_keep（b1 产出，不用于改写 known）
        self._first_seen: dict[str, int] = {}         # canonical -> 首次确立 canonical 的 chunk_id
        self._canonical_chunks: dict[str, set[int]] = {}    # canonical -> 出现过的 chunk_id 集合
        self._canonical_chapters: dict[str, set[int]] = {}  # canonical -> 出现过的 chapter_id 集合
        self._current_chunk_id: int = 0
        self._current_chapter_id: int = 0
```

- [ ] **Step 2: `resolve()` 记录 chunk/chapter 上下文 + 旁路收集 evidence**

在 `resolve()` 开头（L29 `pending` 前）设置当前 chunk 上下文：

```python
        self._current_chunk_id = chunk.chunk_id
        self._current_chapter_id = chunk.chapter_id
```

在 `resolve()` 的 `if pending:`（judge 调用）之前插入 evidence 收集（established 快照已在函数内）：

```python
        # ---- V0.2.3-b1：桥接 mention 旁路收集（纯观察，不改任何状态）----
        established = {c for c in self.known if self.known[c] == c}
        for p in pending:
            hits = [c.canonical for c in p.candidates if c.canonical in established]
            if len(hits) >= 2:
                for i in range(len(hits)):
                    for j in range(i + 1, len(hits)):
                        self.merge_evidence.append({
                            "mention": p.mention,
                            "candidates": list(hits),
                            "pair": [hits[i], hits[j]],
                            "chunk_id": chunk.chunk_id,
                            "chapter_id": chunk.chapter_id,
                            "text": chunk.text,
                        })
```

- [ ] **Step 3: `_register` 记录 first_seen；resolve 末尾统计 canonical 出现**

在 `_register`（L191-195）中追加 first_seen：

```python
    def _register(self, name: str):
        """name 成为新的 canonical（首次出现）。"""
        self.known[name] = name
        self.canonical_aliases.setdefault(name, [])
        self._index.setdefault(name, set()).add(name)
        # V0.2.3-b1：首次确立 canonical 的 chunk_id（非原文首次出现位置）
        self._first_seen.setdefault(name, self._current_chunk_id)
```

在 `resolve()` 的二次替换后（L73-78 区域，`name_map` 应用之后、构造 `resolved` 之前）追加统计：

```python
        # V0.2.3-b1：canonical 出现统计（轻量 metadata，供 merge judge 输入）
        for c in resolved_chars:
            canon = c["name"]
            self._canonical_chunks.setdefault(canon, set()).add(chunk.chunk_id)
            self._canonical_chapters.setdefault(canon, set()).add(chunk.chapter_id)
```

- [ ] **Step 4: 新增 `decide_merges` 与 `resolve_merge_root`（文件末尾，`_add_alias` 之后）**

```python
    # ---- V0.2.3-b1：canonical merge decision（纯 decision，基于 snapshot，不修改 known/_index/canonical_aliases）----

    def decide_merges(self, merge_judge, confidence_threshold: float = 0.5) -> dict:
        """基于 resolve 完成后的 canonical metadata 快照构建 merge_map。

        - 纯 decision：不修改 known/_index/canonical_aliases；不提前应用 merge_map；
        - 所有 pair 基于同一份快照独立判定，不做传递合并；
        - judge failure / confidence 低于阈值 → 不 merge（计入统计）。
        返回 {"merge_map", "stats", "merge_failures"}。
        """
        from app.schemas.llm import BridgeEvidence, MergePair, MergePairSide

        # 1) pair 去重：frozenset(pair) -> evidence 列表（同 pair 只判一次）
        pair_evidences: dict[frozenset, list[dict]] = {}
        for ev in self.merge_evidence:
            key = frozenset(ev["pair"])
            pair_evidences.setdefault(key, []).append(ev)

        # 2) 从 canonical snapshot 构造 judge 输入（不因其他 pair 的判定变化）
        pairs_input: list[MergePair] = []
        for key, evs in pair_evidences.items():
            c1, c2 = tuple(key)
            if c1 not in self.known or c2 not in self.known:
                continue
            sides = []
            for c in (c1, c2):
                sides.append(MergePairSide(
                    canonical=c,
                    aliases=list(self.canonical_aliases.get(c, [])),
                    first_seen_chunk=self._first_seen.get(c, 0),
                    mention_count=len(self._canonical_chunks.get(c, set())),
                    chapters=sorted(self._canonical_chapters.get(c, set())),
                ))
            pairs_input.append(MergePair(
                a=sides[0], b=sides[1],
                bridge_evidence=[BridgeEvidence(
                    chunk_id=e["chunk_id"], chapter_id=e["chapter_id"],
                    mention=e["mention"], text=e["text"],
                ) for e in evs],
            ))

        stats = {"merge_candidate_pairs": len(pairs_input),
                 "merged_pairs": 0, "rejected_pairs": 0, "failed_pairs": 0}
        merge_failures: list[dict] = []

        if not pairs_input:
            return {"merge_map": dict(self.merge_map),
                    "stats": {"entity_resolution": stats}, "merge_failures": merge_failures}

        # 3) batch merge judge
        try:
            result = merge_judge(pairs_input)
        except Exception as exc:
            stats["failed_pairs"] = len(pairs_input)
            merge_failures.append({"error": f"{type(exc).__name__}:{exc}"})
            return {"merge_map": dict(self.merge_map),
                    "stats": {"entity_resolution": stats}, "merge_failures": merge_failures}

        # 4) 过滤 + 构建 merge_map（C_keep = first_seen 更小；相同按 canonical 字符串升序）
        valid_keys = {frozenset((p.a.canonical, p.b.canonical)) for p in pairs_input}
        for d in result.merges:
            key = frozenset((d.a, d.b))
            if key not in valid_keys:
                continue  # 约束：a/b 必须来自输入 pairs
            if not d.merge or d.confidence < confidence_threshold:
                stats["rejected_pairs"] += 1
                continue
            c1, c2 = tuple(key)
            # 确定性 keep：first_seen 更小者；相同 → canonical 字符串升序较小者
            if (self._first_seen.get(c1, 0), c1) <= (self._first_seen.get(c2, 0), c2):
                keep, drop = c1, c2
            else:
                keep, drop = c2, c1
            self.merge_map[drop] = keep
            stats["merged_pairs"] += 1

        return {"merge_map": dict(self.merge_map),
                "stats": {"entity_resolution": stats}, "merge_failures": merge_failures}

    def resolve_merge_root(self, name: str) -> str:
        """沿 merge_map 解析最终 keep（仅查询，不创建新合并）。"""
        seen: set[str] = set()
        while name in self.merge_map and name not in seen:
            seen.add(name)
            name = self.merge_map[name]
        return name
```

- [ ] **Step 5: 运行 b1 测试确认绿**

Run: `cd backend && python -m pytest tests/unit/test_merge.py -v`

Expected: 11 个全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/resolver.py
git commit -m "feat(resolver): V0.2.3-b1 canonical merge decision（bridge evidence → merge_map，纯 decision）"
```

---

### Task 4: merge judge 调用（llm_client.py）

**Files:**
- Modify: `backend/app/pipeline/llm_client.py`

**Interfaces:**
- Consumes: `MergePair`/`MergeJudgeResult`（Task 1）
- Produces: `LLMClient.judge_merges(pairs: list[MergePair]) -> MergeJudgeResult`（复用 429/5xx 重试 1 次模式）

- [ ] **Step 1: 追加 merge judge prompt 常量**

在 `ALIAS_JUDGE_USER_PROMPT`（L37）之后追加：

```python
MERGE_JUDGE_SYSTEM_PROMPT = """你是小说人物实体合并判定器。给定若干对「待判定是否同一人的两个人物」及其桥接证据，判断每对人物是否指向同一人。
严格要求：
1. 只依据提供的两侧人物信息与桥接证据判断，不要使用任何外部小说知识。
2. 每对人物输出一条判定；a/b 必须原样来自输入，禁止修改、禁止创造新名字。
3. merge 必须是布尔值：true 表示同一人，false 表示不同人。
4. confidence 是 0 到 1 之间的浮点数，表示你对判定的把握程度。
5. 只输出 JSON：{"merges": [{"a": "...", "b": "...", "merge": true, "confidence": 0.9}]}"""

MERGE_JUDGE_USER_PROMPT = """待判定人物对：
{pairs}

请输出判定结果。"""
```

- [ ] **Step 2: 追加 `judge_merges` 方法（`judge_aliases` 之后）**

```python
    def judge_merges(self, pairs: list["MergePair"]) -> "MergeJudgeResult":
        """批量判定 canonical 是否同一人（V0.2.3-b1）。429/5xx 重试 1 次；validation 不重试。"""
        from app.schemas.llm import MergeJudgeResult
        pairs_json = json.dumps(
            [{"a": {"canonical": p.a.canonical, "aliases": p.a.aliases,
                    "first_seen_chunk": p.a.first_seen_chunk,
                    "mention_count": p.a.mention_count, "chapters": p.a.chapters},
              "b": {"canonical": p.b.canonical, "aliases": p.b.aliases,
                    "first_seen_chunk": p.b.first_seen_chunk,
                    "mention_count": p.b.mention_count, "chapters": p.b.chapters},
              "bridge_evidence": [{"chunk_id": e.chunk_id, "chapter_id": e.chapter_id,
                                   "mention": e.mention, "text": e.text}
                                  for e in p.bridge_evidence]}
             for p in pairs],
            ensure_ascii=False,
        )
        for attempt in range(2):  # 首次 + 重试 1 次
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": MERGE_JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": MERGE_JUDGE_USER_PROMPT.format(pairs=pairs_json)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                self._log_error("merge_judge", response)
                if attempt == 0:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMRetryableError(f"http_{response.status_code}")
            if response.status_code >= 400:
                self._log_error("merge_judge", response)
                raise LLMError(f"http_{response.status_code}")
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                self._log_error("merge_judge", response, "invalid_response_shape")
                raise LLMValidationError("invalid_response_shape") from exc
            try:
                return MergeJudgeResult.model_validate_json(content)
            except ValidationError as exc:
                self._log_error("merge_judge", response, "validation_error")
                raise LLMValidationError("validation_error") from exc
```

- [ ] **Step 3: 验证现有 llm_client 测试不破坏 + 新增 judge_merges 冒烟测试**

在 `backend/tests/unit/test_llm_client.py` 追加（若文件存在 mock http 模式，按现有模式；否则跳过——b1 测试已用 mock judge，llm_client 契约由 Task 1 schema 验证覆盖）。

Run: `cd backend && python -m pytest tests/unit/test_llm_client.py -v`

Expected: 现有测试全部 PASS（无新增测试则无变化）。

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/llm_client.py
git commit -m "feat(llm_client): V0.2.3-b1 judge_merges（独立契约，429/5xx 重试）"
```

---

### Task 5: 回归验证（不动 b2 / Neo4j / PersonAgg / upsert_graph）

**Files:**
- Test: `backend/tests/unit/test_merge.py`、`backend/tests/unit/test_resolver.py`、`backend/tests/unit/` 全量

**Interfaces:**
- Consumes: Task 1-4 全部
- Produces: 回归结论

- [ ] **Step 1: 运行 merge + resolver 全量**

Run: `cd backend && python -m pytest tests/unit/test_merge.py tests/unit/test_resolver.py -v`

Expected: 全部 PASS（11 + 23 = 34）。

- [ ] **Step 2: unit 全量**

Run: `cd backend && python -m pytest 2>&1 | Select-Object -Last 6`

Expected: 既有基线外全部 PASS（已知：`test_config.py` 2 个失败为既有基线，非本次引入）。

- [ ] **Step 3: 确认未触碰范围**

Run: `cd backend && git diff --stat HEAD~4`

Expected: 只含 `schemas/llm.py`、`tests/unit/test_merge.py`、`pipeline/resolver.py`、`pipeline/llm_client.py`、`tests/unit/test_llm_client.py`（如有）。**无** `merger.py`、`db/neo4j.py`、`api/`、前端文件。

- [ ] **Step 4: 无额外 commit（回归不改代码）**

---

## Self-Review

**1. Spec 覆盖（对照设计文档 §3）：**
- bridge evidence 结构（mention/candidates/pair/chunk_id/chapter_id/text）→ Task 2 测试 11 + Task 3 Step 2 ✓
- first_seen = 首次确立 canonical 的 chunk_id → Task 3 Step 3 `_register` 记录 ✓
- confidence threshold 可配置 → `decide_merges(merge_judge, confidence_threshold=0.5)` 参数 ✓
- b1 纯 decision（不改 known/_index/canonical_aliases）→ Task 3 Step 4 只写 merge_map；测试 10 锁死 ✓
- snapshot 独立判定、不提前应用 merge_map、不传递合并 → Task 3 Step 4 无 merge_map 读取/应用逻辑；测试 8 幂等 ✓
- judge failure → 不 merge，不写 failed_blocks → Task 3 Step 4 try/except + stats ✓
- C_keep = first_seen 更小者 + 确定性 tie-break → Task 3 Step 4 `(first_seen, canonical)` 元组 ✓
- pair 去重、O(mentions×k²) 无全局 O(N²) → Task 3 Step 4 frozenset 分组；测试 4/9 ✓

**2. Placeholder 扫描：** 无 TBD/TODO；每步含完整代码与命令。

**3. 类型一致性：** `decide_merges(merge_judge, confidence_threshold=0.5)` 在测试与实现中签名一致；`merge_evidence` 结构在测试注入与实现收集一致（dict 键 mention/candidates/pair/chunk_id/chapter_id/text）；`_MergeJudge.__call__(pairs)` 接收 `list[MergePair]`，实现传入 `pairs_input` 一致。
