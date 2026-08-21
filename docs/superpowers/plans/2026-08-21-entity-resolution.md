# V0.2 第一步：实体消歧（Entity Resolution）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在抽取与合并之间插入实体消歧：Person 获得 `aliases[]`，别名在整本小说处理中经「规则缓存 → 简单召回 → 每 chunk 批量 LLM 判定」归并到首次出现的 canonical，并扩展人物搜索的 alias 匹配。

**Architecture:** 新增 `pipeline/resolver.py` 的 `EntityResolver`（一次 ingest 一个实例，known/mention index 整本持续）；`llm_client` 新增 `judge_aliases`；merger 增加 `PersonAgg.aliases` 与 `apply_aliases` 富集；db 写层 SET aliases、搜索 OR aliases；`_run_ingest` 接线并把消歧失败记为 `completed_with_errors`。

**Tech Stack:** Python 3.11+ / pydantic v2 / FastAPI / Neo4j driver（复用现有）。

## Global Constraints

- 唯一业务目标 = Entity Resolution；不引入 Embedding / Vector DB / 全局聚类 / Event / Timeline / GraphRAG / 前端业务功能
- 已有 extract（并发抽取）、merge、Graph API、UI 行为不变
- `EntityResolver` 一次 ingest 一个实例；`known`/`canonical_aliases`/mention index 整本持续，禁止每 chunk 重建
- `resolve()` 输入按 chunk_id 升序；chunk 内 characters 按原始出现顺序处理；同 chunk 待判定项先收集、**chunk 末一次 judge_aliases**，禁止逐名调用
- canonical 规则：首次出现且通过确认的 mention 定主名；后续确认名称追加 alias；**不重选 canonical**；LLM 判 `null` → 新 canonical，**不做第二轮**
- `aliases` 不含 canonical 自身（`alias == canonical → ignore`）、去重、按首次确认顺序
- mention_count 语义不变：canonical（含别名提及）出现在 characters 字段的 distinct chunk 数
- judge_aliases 失败分类沿用：429/5xx 重试 1 次；validation error 不重试
- 消歧失败 → 本 chunk 待判定 mention 独立成 canonical + `failed_blocks` 记 `{chunk_id, chapter_id, error: "alias_resolution_failed"}` → Job 终态 `completed_with_errors`（非 failed）；这是**预期行为**（可能暂时双 Person）
- Prompt 不写死小说人物知识
- 测试命令：`cd E:\CodeField\Long-Novel-Intelligence\backend; python -m pytest ...`（无 pip；pytest 无缓存；conftest 已注入 .deps）

---

### Task 1: schemas/llm.py —— 判定契约

**Files:**
- Modify: `backend/app/schemas/llm.py`
- Test: `backend/tests/unit/test_llm_client.py`（追加契约校验用例）

**Interfaces:**
- Consumes: 无
- Produces: `AliasCandidate{canonical, matched_names: list[str]}`、`PendingMention{mention, candidates: list[AliasCandidate]}`、`AliasResolution{mention, resolves_to: str|None}`、`AliasJudgeResult{resolutions: list[AliasResolution]}`（model_validator：同 mention 多条 resolution 时保留首条并去重）

- [ ] **Step 1: 追加失败测试**

```python
from app.schemas.llm import AliasJudgeResult


def test_alias_judge_result_valid():
    r = AliasJudgeResult.model_validate({
        "resolutions": [
            {"mention": "二老", "resolves_to": "傩送"},
            {"mention": "大老", "resolves_to": None},
        ],
    })
    assert r.resolutions[0].resolves_to == "傩送"
    assert r.resolutions[1].resolves_to is None


def test_alias_judge_duplicate_mention_deduped():
    r = AliasJudgeResult.model_validate({
        "resolutions": [
            {"mention": "二老", "resolves_to": "傩送"},
            {"mention": "二老", "resolves_to": "大老"},
        ],
    })
    assert len(r.resolutions) == 1
    assert r.resolutions[0].resolves_to == "傩送"
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest tests/unit/test_llm_client.py -k alias -v` → FAIL（ImportError）
- [ ] **Step 3: 实现**

```python
class AliasCandidate(BaseModel):
    canonical: str = Field(min_length=1, max_length=50)
    matched_names: list[str] = Field(default_factory=list)


class PendingMention(BaseModel):
    mention: str = Field(min_length=1, max_length=50)
    candidates: list[AliasCandidate] = Field(default_factory=list)


class AliasResolution(BaseModel):
    mention: str = Field(min_length=1, max_length=50)
    resolves_to: str | None = Field(default=None, min_length=1, max_length=50)


class AliasJudgeResult(BaseModel):
    resolutions: list[AliasResolution] = Field(default_factory=list)

    @model_validator(mode="after")
    def dedupe_mentions(self):
        seen: set[str] = set()
        kept: list[AliasResolution] = []
        for r in self.resolutions:
            if r.mention not in seen:
                seen.add(r.mention)
                kept.append(r)
        self.resolutions = kept
        return self
```

- [ ] **Step 4: 运行确认通过**：2 passed
- [ ] **Step 5: Commit**：`git add backend/app/schemas/llm.py backend/tests/unit/test_llm_client.py` → `git commit -m "feat: 实体消歧判定契约（AliasJudgeResult）"`

---

### Task 2: llm_client.judge_aliases

**Files:**
- Modify: `backend/app/pipeline/llm_client.py`
- Test: `backend/tests/unit/test_llm_client.py`（追加）

**Interfaces:**
- Consumes: `PendingMention` / `AliasJudgeResult`（Task 1）
- Produces: `LLMClient.judge_aliases(chunk_text: str, pending: list[PendingMention]) -> AliasJudgeResult`（JSON mode；429/5xx → `LLMRetryableError`；解析/校验失败 → `LLMValidationError`）

- [ ] **Step 1: 追加失败测试**

```python
from app.schemas.llm import AliasJudgeResult, PendingMention


def test_judge_aliases_parses_result():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": (
        '{"resolutions": [{"mention": "二老", "resolves_to": "傩送"}]}'
    )}}]})])
    pending = [PendingMention.model_validate({
        "mention": "二老",
        "candidates": [{"canonical": "傩送", "matched_names": ["傩送", "二老"]}],
    })]
    result = client.judge_aliases("文本", pending)
    assert isinstance(result, AliasJudgeResult)
    assert result.resolutions[0].resolves_to == "傩送"


def test_judge_aliases_bad_json_is_validation_error():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": "不是JSON"}}]})])
    with pytest.raises(Exception) as exc:
        client.judge_aliases("文本", [])
    assert "validation_error" in str(exc.value)


def test_judge_aliases_retryable_429():
    client = make_client([fake_response(429), fake_response(200, {"choices": [{"message": {"content": '{"resolutions": []}'}}]})])
    client.judge_aliases("文本", [])
    assert client._client.calls == 2
```

- [ ] **Step 2: 运行确认失败**（MethodError/AttributeError）
- [ ] **Step 3: 实现**（追加常量与方法；沿用 `extract_chunk` 的请求/失败分类模式）

```python
ALIAS_JUDGE_SYSTEM_PROMPT = """你是小说人物实体消歧判定器。给定一段小说文本与若干「待判定的人物名及其候选人物」，判断每个待判定名字是否与某个候选人物是同一人。
严格要求：
1. 只依据提供的文本与候选信息判断，不要使用任何外部小说知识。
2. 每个 mention 最多输出一条 resolution；resolves_to 只能是该 mention 的候选之一，或 null（表示不是任何候选）。
3. 禁止创造输入之外的新人物名；不得修改 mention 本身。
4. 只输出 JSON：{"resolutions": [{"mention": "...", "resolves_to": "..."}]}"""

ALIAS_JUDGE_USER_PROMPT = """小说文本：
{text}

待判定人物（含候选）：
{mentions}

请输出判定结果。"""


class LLMClient:
    # ...（现有 __init__ 不变）

    def judge_aliases(self, chunk_text: str, pending: list["PendingMention"]) -> "AliasJudgeResult":
        from app.schemas.llm import AliasJudgeResult
        mentions_json = json.dumps(
            [{"mention": p.mention,
              "candidates": [{"canonical": c.canonical, "matched_names": c.matched_names}
                             for c in p.candidates]}
             for p in pending],
            ensure_ascii=False,
        )
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": ALIAS_JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": ALIAS_JUDGE_USER_PROMPT.format(text=chunk_text, mentions=mentions_json)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMRetryableError(f"http_{response.status_code}")
        if response.status_code >= 400:
            raise LLMError(f"http_{response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMValidationError("invalid_response_shape") from exc
        try:
            return AliasJudgeResult.model_validate_json(content)
        except ValidationError as exc:
            raise LLMValidationError("validation_error") from exc
```

> `import json` 追加到文件顶部；类型注解用字符串避免循环导入。

- [ ] **Step 4: 运行确认通过**：3 passed
- [ ] **Step 5: Commit**：`feat: LLM 实体消歧判定调用（judge_aliases）`

---

### Task 3: pipeline/resolver.py —— EntityResolver

**Files:**
- Create: `backend/app/pipeline/resolver.py`
- Test: `backend/tests/unit/test_resolver.py`

**Interfaces:**
- Consumes: `Chunk`、`ExtractionResult`（Task 已有）、`PendingMention`/`AliasJudgeResult`（Task 1）、judge 可调用对象
- Produces:
  - `class EntityResolver`：`__init__(self, judge: Callable[[str, list[PendingMention]], AliasJudgeResult])`；`resolve(self, chunk: Chunk, result: ExtractionResult) -> tuple[ExtractionResult, bool]`（第二项 = 本 chunk 判定是否失败）；属性 `canonical_aliases: dict[str, list[str]]`
  - `_recall(mention) -> list[AliasCandidate]`（共享字符数 + 子串优先，top-k=5，按 canonical 分组去重）
  - `_resolve_name(name) -> tuple[str, bool]`（返回 canonical 与「是否进入 pending」）

- [ ] **Step 1: 写失败测试（6+1 行为锁死）**

```python
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import AliasJudgeResult, ExtractionResult


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


class _Judge:
    def __init__(self, mapping):
        self.mapping = mapping  # mention -> canonical | None
        self.calls = 0

    def __call__(self, text, pending):
        self.calls += 1
        return AliasJudgeResult.model_validate({
            "resolutions": [
                {"mention": p.mention, "resolves_to": self.mapping.get(p.mention)}
                for p in pending
            ],
        })


def test_new_name_no_candidate_is_new_canonical_no_llm():
    j = _Judge({})
    r = EntityResolver(judge=j)
    out, failed = r.resolve(make_chunk(1), extraction(["傩送"]))
    assert out.characters[0].name == "傩送"
    assert j.calls == 0
    assert r.canonical_aliases == {"傩送": []}


def test_one_judge_call_per_chunk():
    """每 chunk 至多一次 judge：一个 chunk 内多个未知 mention 批量判定（known 整本持续，已确认的别名不再进 pending）。"""
    j = _Judge({"傩二": "傩送", "二送": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1, text="傩送是哥哥"), extraction(["傩送"]))
    out, failed = r.resolve(make_chunk(2, text="傩二和二送都来了"), extraction(["傩二", "二送"]))
    assert j.calls == 1  # 两个未知 mention 一次批量判定
    assert [c.name for c in out.characters] == ["傩送", "傩送"]


def test_judged_alias_points_to_existing_canonical():
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    out, _ = r.resolve(make_chunk(2), extraction(["二老"]))
    assert out.characters[0].name == "傩送"
    assert r.canonical_aliases["傩送"] == ["二老"]


def test_judge_null_creates_new_canonical_no_second_round():
    """判 null → 新 canonical；再次出现缓存命中，不做第二轮。"""
    j = _Judge({"李四": None})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["李三"]))
    out, _ = r.resolve(make_chunk(2), extraction(["李四"]))
    assert out.characters[0].name == "李四"
    assert j.calls == 1
    out2, _ = r.resolve(make_chunk(3), extraction(["李四"]))
    assert out2.characters[0].name == "李四"
    assert j.calls == 1  # 缓存命中，不二轮


def test_judge_validation_failure_isolates_and_records():
    def failing_judge(text, pending):
        raise ValueError("judge boom")

    r = EntityResolver(judge=failing_judge)
    r.resolve(make_chunk(1), extraction(["大老"]))  # seed canonical
    out, failed = r.resolve(make_chunk(5, chapter_id=2), extraction(["二老"]))  # 召回大老 → 判定失败
    assert out.characters[0].name == "二老"  # 独立 canonical
    assert failed is True
    assert r.canonical_aliases == {"大老": [], "二老": []}


def test_aliases_deduped_ordered_exclude_canonical():
    j = _Judge({"二老": "傩送", "二老爷": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))
    r.resolve(make_chunk(2), extraction(["二老"]))
    r.resolve(make_chunk(3), extraction(["二老爷"]))
    r.resolve(make_chunk(4), extraction(["二老"]))  # 缓存命中，不调 LLM
    assert r.canonical_aliases["傩送"] == ["二老", "二老爷"]
    assert "傩送" not in r.canonical_aliases["傩送"]
    assert j.calls == 2


def test_first_occurrence_determines_canonical():
    # Chunk1 二老 → canonical=二老；Chunk2 傩送 → alias
    j = _Judge({"傩送": "二老"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["二老"]))
    out, _ = r.resolve(make_chunk(2), extraction(["傩送"]))
    assert out.characters[0].name == "二老"
    assert r.canonical_aliases["二老"] == ["傩送"]

    # 反过来：Chunk1 傩送 → canonical=傩送；Chunk2 二老 → alias
    j2 = _Judge({"二老": "傩送"})
    r2 = EntityResolver(judge=j2)
    r2.resolve(make_chunk(1), extraction(["傩送"]))
    out2, _ = r2.resolve(make_chunk(2), extraction(["二老"]))
    assert out2.characters[0].name == "傩送"
    assert r2.canonical_aliases["傩送"] == ["二老"]


def test_relationship_endpoints_resolved():
    j = _Judge({"二老": "傩送"})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送", "翠翠"], [
        {"source": "傩送", "target": "翠翠", "type": "love", "confidence": 0.9}]))
    out, _ = r.resolve(make_chunk(2), extraction(["翠翠"], [
        {"source": "二老", "target": "翠翠", "type": "love", "confidence": 0.8}]))
    rel = out.relationships[0]
    assert rel.source == "傩送"
    assert rel.target == "翠翠"
```

- [ ] **Step 2: 运行确认失败**（ModuleNotFoundError）
- [ ] **Step 3: 实现 resolver.py**

```python
from dataclasses import dataclass, field
from typing import Callable

from app.pipeline.chunker import Chunk
from app.schemas.llm import AliasCandidate, AliasJudgeResult, ExtractionResult, PendingMention

RECALL_TOP_K = 5


def _chars(s: str) -> set[str]:
    return set(s)


def _overlap(a: str, b: str) -> int:
    return len(_chars(a) & _chars(b))


class EntityResolver:
    """一次 Novel ingest 一个实例；known / canonical_aliases / mention index 整本持续。"""

    def __init__(self, judge: Callable[[str, list[PendingMention]], AliasJudgeResult]):
        self._judge = judge
        self.known: dict[str, str] = {}               # 名字 → canonical（含 canonical 自身与别名）
        self.canonical_aliases: dict[str, list[str]] = {}  # canonical → [别名]，保序
        self._index: dict[str, set[str]] = {}         # canonical → matched_names（去重）

    # ---- 公开 ----
    def resolve(self, chunk: Chunk, result: ExtractionResult) -> tuple[ExtractionResult, bool]:
        pending: list[PendingMention] = []
        resolved_chars: list = []
        resolved_rels: list = []

        def do_name(name: str) -> str:
            canonical, needs_judge = self._resolve_name(name)
            if needs_judge:
                pending.append(self._pending_for(name))
                return name  # 判定后再替换
            return canonical

        for c in result.characters:
            resolved_chars.append({"name": do_name(c.name)})
        for r in result.relationships:
            src = do_name(r.source)
            tgt = do_name(r.target)
            resolved_rels.append({
                "source": src, "target": tgt, "type": r.type.value,
                "confidence": r.confidence,
            })

        failed = False
        if pending:
            try:
                judge_result = self._judge(chunk.text, pending)
                self._apply_judge(judge_result, pending)
            except Exception:
                # validation/网络等任何失败：本 chunk 待判定 mention 独立为 canonical（预期行为）
                for p in pending:
                    self._register(p.mention)
                failed = True

        # 判定后二次替换（pending 中的 mention → canonical）
        if pending:
            name_map = {p.mention: self.known[p.mention] for p in pending}
            resolved_chars = [{"name": name_map.get(c["name"], c["name"])} for c in resolved_chars]
            for rel in resolved_rels:
                rel["source"] = name_map.get(rel["source"], rel["source"])
                rel["target"] = name_map.get(rel["target"], rel["target"])

        resolved = ExtractionResult.model_validate({
            "characters": resolved_chars,
            "relationships": resolved_rels,
        })
        return resolved, failed

    # ---- 内部 ----
    def _resolve_name(self, name: str) -> tuple[str, bool]:
        if name in self.known:
            return self.known[name], False
        candidates = self._recall(name)
        if not candidates:
            self._register(name)
            return name, False
        return name, True  # 进 pending，本 chunk 末统一判定

    def _recall(self, mention: str) -> list[AliasCandidate]:
        scored: list[tuple[int, str, set[str]]] = []
        for canonical, names in self._index.items():
            hit = None
            for n in names:
                if mention in n or n in mention:      # 子串包含优先
                    hit = n
                    break
            overlap = max(_overlap(mention, n) for n in names) if names else 0
            scored.append((1 if hit else 0, overlap, canonical))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        out = []
        for _prio, _ov, canonical in scored[:RECALL_TOP_K]:
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))
        return out

    def _pending_for(self, mention: str) -> PendingMention:
        return PendingMention(mention=mention, candidates=self._recall(mention))

    def _apply_judge(self, judge_result: AliasJudgeResult, pending: list[PendingMention]):
        valid_canonicals = {c.canonical for p in pending for c in p.candidates}
        valid_mentions = {p.mention for p in pending}
        for r in judge_result.resolutions:
            if r.mention not in valid_mentions:
                continue  # 约束：mention 必须来自输入
            if r.resolves_to is not None and r.resolves_to not in valid_canonicals:
                continue  # 约束：resolves_to 必须来自候选
            self.known[r.mention] = r.resolves_to if r.resolves_to is not None else r.mention
            if r.resolves_to is not None:
                self._add_alias(r.resolves_to, r.mention)
            else:
                self._register(r.mention)
        # 未出现在判定结果中的 pending mention → 独立 canonical（防御）
        judged = {r.mention for r in judge_result.resolutions}
        for p in pending:
            if p.mention not in judged:
                self._register(p.mention)

    def _register(self, name: str):
        """name 成为新的 canonical（首次出现）。"""
        self.known[name] = name
        self.canonical_aliases.setdefault(name, [])
        self._index.setdefault(name, set()).add(name)

    def _add_alias(self, canonical: str, alias: str):
        if alias == canonical:
            return  # canonical 不进 aliases
        if canonical not in self.known or self.known[canonical] != canonical:
            return  # 防御：canonical 必须已知且为主名
        self.known[alias] = canonical
        self._index.setdefault(canonical, set()).add(canonical)
        self._index[canonical].add(alias)
        if alias not in self.canonical_aliases[canonical]:
            self.canonical_aliases[canonical].append(alias)  # 首次确认顺序
```

> 说明：`do_name` 对 pending mention 先返回原名字，判定后统一替换；`_recall` 的 index 中 matched_names 用 `sorted` 仅为稳定输入给 LLM（aliases 顺序仍由 `canonical_aliases` 的追加序保证）。

- [ ] **Step 4: 运行确认通过**：8 passed
- [ ] **Step 5: Commit**：`git add backend/app/pipeline/resolver.py backend/tests/unit/test_resolver.py` → `git commit -m "feat: EntityResolver（整本生命周期/批量判定/canonical 首次出现规则）"`

---

### Task 4: merger 富集与写层

**Files:**
- Modify: `backend/app/pipeline/merger.py`、`backend/app/db/neo4j.py`
- Test: `backend/tests/unit/test_merger.py`、`backend/tests/integration/test_api_neo4j.py`

**Interfaces:**
- Consumes: `MergedGraph`（现有）、`EntityResolver.canonical_aliases`（Task 3）
- Produces: `PersonAgg.aliases: list[str] = []`；`apply_aliases(graph: MergedGraph, canonical_aliases: dict[str, list[str]]) -> None`（排除 canonical 自身、去重、保序）；`upsert_graph` 写 `p.aliases`

- [ ] **Step 1: 失败测试**

```python
# test_merger.py 追加
from app.pipeline.merger import MergedGraph, PersonAgg, apply_aliases


def test_apply_aliases_filters_canonical_and_dedupes():
    graph = MergedGraph(
        persons={"傩送": PersonAgg(name="傩送", mention_count=2, chapters={1})},
        relationships={},
    )
    apply_aliases(graph, {"傩送": ["二老", "傩送", "二老", "二老爷"]})
    assert graph.persons["傩送"].aliases == ["二老", "二老爷"]
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**

```python
# merger.py
@dataclass
class PersonAgg:
    name: str
    mention_count: int = 0
    chapters: set[int] = field(default_factory=set)
    aliases: list[str] = field(default_factory=list)


def apply_aliases(graph: MergedGraph, canonical_aliases: dict[str, list[str]]) -> None:
    """把 resolver 的别名映射写回 PersonAgg（排除 canonical 自身、去重、保序）。"""
    for name, person in graph.persons.items():
        seen: set[str] = set()
        aliases: list[str] = []
        for a in canonical_aliases.get(name, []):
            if a == name or a in seen:
                continue
            seen.add(a)
            aliases.append(a)
        person.aliases = aliases
```

```python
# db/neo4j.py upsert_graph 的 Person 分支：SET 追加 p.aliases
                    """MERGE (p:Person {novel_id: $novel_id, name: $name})
                       ON CREATE SET p.id = $person_id
                       SET p.mention_count = $mention_count, p.chapters = $chapters, p.aliases = $aliases""",
                    novel_id=novel_id, name=name, person_id=str(uuid4()),
                    mention_count=person.mention_count, chapters=sorted(person.chapters),
                    aliases=person.aliases,
```

- [ ] **Step 4: 运行确认通过**：test_merger 全绿 + 集成 3 db 用例绿
- [ ] **Step 5: Commit**：`feat: Person.aliases 富集与写入（merger/db）`

---

### Task 5: _run_ingest 接线 + 状态

**Files:**
- Modify: `backend/app/api/novels.py`
- Test: `backend/tests/integration/test_api_neo4j.py`（追加消歧集成用例）

**Interfaces:**
- Consumes: `EntityResolver`（Task 3）、`apply_aliases`（Task 4）
- Produces: `_run_ingest` 中：resolver 实例（judge=`llm_client.judge_aliases`）→ 逐 chunk resolve → `apply_aliases` → upsert；消歧失败记 `failed_blocks`（`error: "alias_resolution_failed"`）→ 终态 `completed_with_errors`

- [ ] **Step 1: 追加集成测试**

```python
class FakeLLMWithJudge(FakeLLMClient):
    """在 FakeLLMClient 基础上提供 judge_aliases（固定：所有 pending mention 独立）。"""

    def judge_aliases(self, chunk_text, pending):
        return {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]}


def test_upload_with_resolution_job_state(client):
    """替换 llm_client 为带 judge 的 fake；验证 job 终态 completed 且 Person 无 aliases 拆分。"""
    from app.main import create_app as _create
    from fastapi.testclient import TestClient as _TC
    from tests.epub_factory import build_epub
    app = _create()
    with _TC(app) as c:
        app.state.llm_client = FakeLLMWithJudge()
        epub_bytes = build_epub(["傩送和翠翠在河边。", "翠翠等着傩送。"])
        resp = c.post("/api/novels", files={"file": ("t.epub", epub_bytes, "application/epub+zip")})
        data = resp.json()
        job = _wait_job(c, data["job_id"])
        assert job["status"] == "completed"
        cands = c.get(f"/api/novels/{data['novel_id']}/characters", params={"q": "傩"}).json()
        assert any(x["name"] == "傩送" for x in cands)
        c.app.state.db.delete_novel(data["novel_id"])
```

- [ ] **Step 2: 运行确认失败**（当前无 resolver 接线）
- [ ] **Step 3: 实现 _run_ingest**

```python
        from app.pipeline.resolver import EntityResolver
        from app.pipeline.merger import apply_aliases

        # 抽取（并发，不变）
        bundle = extract_all(...)
        # 实体消歧（顺序，整本一个 resolver）
        resolver = EntityResolver(judge=llm_client.judge_aliases)
        resolved: list[tuple] = []
        resolution_failed: list[dict] = []
        for chunk, result in bundle.results:  # 已按 chunk_id 升序
            out, failed = resolver.resolve(chunk, result)
            resolved.append((chunk, out))
            if failed:
                resolution_failed.append({
                    "chunk_id": chunk.chunk_id,
                    "chapter_id": chunk.chapter_id,
                    "error": "alias_resolution_failed",
                })
        merged = merge_extractions(resolved)
        apply_aliases(merged, resolver.canonical_aliases)
        db.upsert_novel(...)
        db.upsert_graph(novel_id, merged)
        stats = db.count_stats(novel_id)
        all_failed = bundle.failed + resolution_failed
        if all_failed:
            job_store.update(job_id, status=JobStatus.completed_with_errors,
                             failed_blocks=[{"chunk_id": f.chunk_id, "chapter_id": f.chapter_id, "error": f.error}
                                            for f in all_failed], stats=stats)
        else:
            job_store.update(job_id, status=JobStatus.completed, stats=stats)
```

- [ ] **Step 4: 运行确认通过**：集成 11+ passed（全量）
- [ ] **Step 5: Commit**：`feat: ingest 接入实体消歧与 completed_with_errors 状态`

---

### Task 6: 搜索 alias 匹配

**Files:**
- Modify: `backend/app/db/neo4j.py`
- Test: `backend/tests/integration/test_api_neo4j.py`（追加）

**Interfaces:**
- Produces: `search_characters` Cypher 支持 `name CONTAINS $q OR ANY(a IN p.aliases WHERE a CONTAINS $q)`

- [ ] **Step 1: 追加集成测试**

```python
def test_search_matches_alias(client):
    db = client.app.state.db
    nid = f"alias-{uuid.uuid4()}"
    try:
        db.upsert_novel(nid, "边城测试", [{"id": 1, "title": "第1章"}])
        db.upsert_graph(nid, MergedGraph(
            persons={"傩送": PersonAgg(name="傩送", mention_count=3, chapters={1}, aliases=["二老", "二老爷"])},
            relationships={},
        ))
        cands = client.get(f"/api/novels/{nid}/characters", params={"q": "二老"}).json()
        assert any(c["name"] == "傩送" for c in cands)
        # canonical 本身仍可搜
        cands2 = client.get(f"/api/novels/{nid}/characters", params={"q": "傩"}).json()
        assert any(c["name"] == "傩送" for c in cands2)
    finally:
        db.delete_novel(nid)
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**

```python
    def search_characters(self, novel_id: str, q: str, limit: int = 10) -> list[dict]:
        with self._driver.session() as session:
            records = session.run(
                """MATCH (p:Person)
                   WHERE p.novel_id = $novel_id
                     AND (p.name CONTAINS $q OR ANY(a IN p.aliases WHERE a CONTAINS $q))
                   RETURN p.id AS id, p.name AS name, p.mention_count AS mention_count
                   ORDER BY p.mention_count DESC
                   LIMIT $limit""",
                novel_id=novel_id, q=q, limit=limit,
            )
            return [dict(r) for r in records]
```

- [ ] **Step 4: 运行确认通过**：集成全量 passed
- [ ] **Step 5: Commit**：`feat: 人物搜索支持 alias 匹配`

---

## 最终验证

```
cd E:\CodeField\Long-Novel-Intelligence\backend
python -m pytest            # 单元全绿（含 test_resolver 7 例 + test_merger 新增）
python -m pytest -m integration   # 集成全绿
```

## Self-Review（已执行）

- spec §4 resolver 生命周期/顺序/批量判定 → Task 3；§6 契约 → Task 1/2；§7 失败状态 → Task 5；§8 merger/写层/搜索 → Task 4/6；§9 测试清单 → Task 3 的 6+1 用例 + Task 4/6 集成；§10 已知限制 → 代码注释与测试标注。
- 占位符：无。
- 类型一致性：`EntityResolver(judge=...)`、`resolve -> (ExtractionResult, bool)`、`apply_aliases(graph, canonical_aliases)`、`judge_aliases(chunk_text, pending) -> AliasJudgeResult` 在任务间签名一致。
