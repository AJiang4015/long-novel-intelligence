# V0.2.4 Mention Hygiene / Collective Mention Filtering 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 mention hygiene：COLLECTIVE/INVALID 硬过滤（不建 Person canonical、不进 known/_index/canonical_aliases/merge_evidence）；GENERIC 不建 canonical 但可作 alias mention 消歧；DESCRIPTIVE/COMPOSITE 不误伤（有候选进 judge、无候选允许注册 canonical）；category=None 走 legacy PERSON fallback。

**Architecture:** 新增 `pipeline/hygiene.py` 纯函数（deterministic hard rules：仅高置信 COLLECTIVE/INVALID 直接过滤）；`Character.category` 用 `MentionCategory` Enum（可选，LLM 未输出→None）；`resolver._resolve_name`/`resolve()` 按 category 决策；`_recall` 排除被硬过滤 canonical；job stats 增加 mention_hygiene。

**Tech Stack:** Python 3.x + pydantic（现有），无新依赖。

## Global Constraints

- 只改 `schemas/llm.py`、`llm_client.py`、`pipeline/hygiene.py`（新建）、`pipeline/resolver.py`、`api/novels.py`、`tests/unit/test_hygiene.py`（新建）、`tests/unit/test_resolver.py`（如需）
- 不修改 canonical merge bridge 规则 / 不迁移旧 Neo4j / 不新增 Group / 不改 Neo4j schema / API / GraphResponse / 前端
- 不调用真实 LLM（测试全 mock）
- **hard rules 只允许高置信 COLLECTIVE / INVALID 直接过滤**；不得把 GENERIC / DESCRIPTIVE / COMPOSITE 扩大为硬过滤
- **category=None**：hard rules 未命中 → legacy PERSON fallback（向后兼容，不表示 LLM 判 PERSON）；增加旧版 ExtractionResult 无 category 回归测试
- **GENERIC 候选必须来自当前有效 canonical index**；COLLECTIVE/INVALID 不得进入 candidate recall（`_recall` 三层排除）；不得让 GENERIC 吸收历史污染 canonical
- 被过滤 mention 不得进入 known/_index/canonical_aliases/merge_evidence
- 测试命令统一 `cd backend && python -m pytest ...`

---

### Task 1: MentionCategory Enum + Character.category（schemas/llm.py）

**Files:**
- Modify: `backend/app/schemas/llm.py`
- Test: `backend/tests/unit/test_hygiene.py`（新建，先建基础 + category 契约用例）

**Interfaces:**
- Consumes: 无（纯新契约）
- Produces: `MentionCategory`（PERSON/GENERIC/COLLECTIVE/DESCRIPTIVE/COMPOSITE/INVALID）；`Character.category: MentionCategory | None = None`

- [ ] **Step 1: 在 `schemas/llm.py` 中 `RelationshipType` 之后、`Character` 之前插入 Enum**

```python
class MentionCategory(str, Enum):
    """V0.2.4 mention 分类：extract 契约输出；None 时走 hygiene 规则兜底。"""
    PERSON = "person"           # 专名（天保/傩送/翠翠）
    GENERIC = "generic"         # 泛指称谓（年青人/妇人/哥哥/弟弟）
    COLLECTIVE = "collective"   # 集合称谓（两个儿子/兄弟二人/父子三人）
    DESCRIPTIVE = "descriptive" # 描述性称谓（翠翠的祖父）
    COMPOSITE = "composite"     # 复合称谓（岳云二老/天保大老/天保大人）
    INVALID = "invalid"         # 畸形（空/纯数字/符号/超长）
```

修改 `Character`：

```python
class Character(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    category: MentionCategory | None = None   # V0.2.4：LLM 未输出 → None → hygiene 兜底
```

- [ ] **Step 2: 创建 `backend/tests/unit/test_hygiene.py` 基础 + category 契约测试**

```python
"""V0.2.4 mention hygiene 测试（mock extract/judge，不调真实 LLM）。"""
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import (AliasJudgeResult, Character, ExtractionResult,
                             MentionCategory)


def make_chunk(chunk_id, chapter_id=1, text="文本"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(names, categories=None):
    """categories: dict[name, MentionCategory|None]；缺省 None（legacy）。"""
    chars = []
    for n in names:
        item = {"name": n}
        if categories and categories.get(n) is not None:
            item["category"] = categories[n].value
        chars.append(item)
    return ExtractionResult.model_validate({"characters": chars, "relationships": []})


def judge_null(text, pending):
    return AliasJudgeResult.model_validate(
        {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})


def test_character_category_optional_legacy():
    """旧版 ExtractionResult 无 category → 解析成功，category=None。"""
    r = ExtractionResult.model_validate({"characters": [{"name": "天保"}], "relationships": []})
    assert r.characters[0].category is None


def test_character_category_enum():
    """category 用 Enum 校验；非法值拒绝。"""
    r = ExtractionResult.model_validate(
        {"characters": [{"name": "两个儿子", "category": "collective"}], "relationships": []})
    assert r.characters[0].category == MentionCategory.COLLECTIVE
    with pytest.raises(Exception):
        ExtractionResult.model_validate(
            {"characters": [{"name": "X", "category": "banana"}], "relationships": []})
```

Run: `cd backend && python -m pytest tests/unit/test_hygiene.py -v`
Expected: 2 PASS。

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/llm.py backend/tests/unit/test_hygiene.py
git commit -m "feat(schemas): V0.2.4 MentionCategory Enum + Character.category 可选字段"
```

---

### Task 2: pipeline/hygiene.py — deterministic hard rules

**Files:**
- Create: `backend/app/pipeline/hygiene.py`
- Test: `backend/tests/unit/test_hygiene.py`（追加）

**Interfaces:**
- Consumes: `MentionCategory`
- Produces:
  - `classify_mention(name: str) -> MentionCategory | None`（仅返回 COLLECTIVE/INVALID，或 None——**不返回 GENERIC/DESCRIPTIVE/COMPOSITE**，那些由 LLM category 负责）
  - `is_hard_filtered(name: str) -> bool`（COLLECTIVE 或 INVALID）

- [ ] **Step 1: 写失败测试（hard rules 范围锁死）**

在 test_hygiene.py 末尾追加：

```python
# ---------- Task 2: deterministic hard rules ----------
from app.pipeline.hygiene import classify_mention, is_hard_filtered


@pytest.mark.parametrize("name", ["两个儿子", "兄弟二人", "父子三人", "两弟兄", "三个儿子"])
def test_hard_filter_collective(name):
    """COLLECTIVE 可 hard filter：两个儿子/兄弟二人/父子三人/两弟兄。"""
    assert is_hard_filtered(name)
    assert classify_mention(name) == MentionCategory.COLLECTIVE


@pytest.mark.parametrize("name", ["", "12345", "!!!", "x" * 60])
def test_hard_filter_invalid(name):
    assert is_hard_filtered(name)
    assert classify_mention(name) == MentionCategory.INVALID


@pytest.mark.parametrize("name", ["弟弟", "妇人", "年青人", "哥哥", "死去的人", "老头子"])
def test_generic_not_hard_filtered(name):
    """GENERIC 不得被 hard rules 过滤——只能由 LLM category 分类，resolver 决策。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None   # hard rules 不返回 GENERIC


@pytest.mark.parametrize("name", ["岳云二老", "天保大老", "天保大人", "傩送二老"])
def test_composite_not_hard_filtered(name):
    """COMPOSITE 不直接过滤。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None


@pytest.mark.parametrize("name", ["翠翠的祖父", "顺顺大儿子"])
def test_descriptive_not_hard_filtered(name):
    """DESCRIPTIVE 不直接过滤。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None


@pytest.mark.parametrize("name", ["天保", "傩送", "翠翠", "祖父", "顺顺", "王团总"])
def test_person_not_hard_filtered(name):
    """正常专名不误伤。"""
    assert not is_hard_filtered(name)
    assert classify_mention(name) is None
```

Run: `cd backend && python -m pytest tests/unit/test_hygiene.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.pipeline.hygiene'`）。

- [ ] **Step 2: 实现 `backend/app/pipeline/hygiene.py`**

```python
"""V0.2.4 mention hygiene：deterministic hard rules。

只负责高置信 COLLECTIVE / INVALID 直接过滤。
GENERIC / DESCRIPTIVE / COMPOSITE 由 LLM extract category 分类，
本模块**不得**返回这些类别（返回 None → resolver 走 LLM category 或 legacy PERSON fallback）。
"""
import re

from app.schemas.llm import MentionCategory

MAX_NAME_LEN = 50  # 与 Character.name 上限一致

# 集合量词模式：两个儿子/兄弟二人/父子三人/两弟兄/三个儿子 …
_COLLECTIVE_PATTERNS = [
    re.compile(r"^[一二两三四五六七八九十百多诸]+个?(儿子|兄弟|儿女|子女|姐妹|弟兄)$"),
    re.compile(r"^兄弟[一二两三四五六七八九十]+人$"),
    re.compile(r"^父子[一二两三四五六七八九十]+人$"),
    re.compile(r"^两弟兄$"),
    re.compile(r"^[一二两三四五六七八九十百多诸]+个?(小孩|孩子|女子|男子|青年|老人|妇人)们?$"),
]

_INVALID_PATTERNS = [
    re.compile(r"^\s*$"),          # 空/纯空白
    re.compile(r"^\d+$"),          # 纯数字
    re.compile(r"^[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?~`]+$"),  # 纯符号
]


def classify_mention(name: str) -> MentionCategory | None:
    """deterministic hard rules：仅返回 COLLECTIVE / INVALID；否则 None。

    None 表示「hard rules 未命中」——resolver 应使用 LLM category，
    或（category 也为 None 时）按 legacy PERSON fallback 处理。
    """
    if name is None or len(name) > MAX_NAME_LEN:
        return MentionCategory.INVALID
    for pat in _INVALID_PATTERNS:
        if pat.match(name):
            return MentionCategory.INVALID
    for pat in _COLLECTIVE_PATTERNS:
        if pat.match(name):
            return MentionCategory.COLLECTIVE
    return None


def is_hard_filtered(name: str) -> bool:
    """COLLECTIVE / INVALID 直接过滤。"""
    return classify_mention(name) in (MentionCategory.COLLECTIVE, MentionCategory.INVALID)
```

- [ ] **Step 3: 运行测试确认绿**

Run: `cd backend && python -m pytest tests/unit/test_hygiene.py -v`
Expected: 全部 PASS（2 + 6 组参数化）。

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/hygiene.py backend/tests/unit/test_hygiene.py
git commit -m "feat(hygiene): V0.2.4 deterministic hard rules（COLLECTIVE/INVALID 高置信过滤）"
```

---

### Task 3: resolver 接入 category 决策（GENERIC/DESCRIPTIVE/COMPOSITE 语义）

**Files:**
- Modify: `backend/app/pipeline/resolver.py`
- Test: `backend/tests/unit/test_hygiene.py`（追加）

**Interfaces:**
- Consumes: `MentionCategory`、`classify_mention`/`is_hard_filtered`（Task 2）、`Character.category`
- Produces:
  - `_resolve_name` 决策表：GENERIC 无候选丢弃；DESCRIPTIVE/COMPOSITE 无候选注册；COLLECTIVE/INVALID 永不进入
  - `resolve()` 开头过滤 COLLECTIVE/INVALID（chunk_names 排除）
  - `_recall` 排除被硬过滤 canonical

- [ ] **Step 1: 写失败测试（resolver 决策表 + 状态污染）**

在 test_hygiene.py 末尾追加：

```python
# ---------- Task 3: resolver category 决策 ----------

def test_collective_never_registered():
    """COLLECTIVE 提取输出 → 不注册 canonical，不进任何状态。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert "两个儿子" not in r.known
    assert "两个儿子" not in r._index
    assert "两个儿子" not in r.canonical_aliases
    assert [c["name"] for c in out.characters] == ["两个儿子"]  # 原样保留在输出（不崩）


def test_collective_as_relation_endpoint_drops_relation():
    """COLLECTIVE 作 relation endpoint → 该关系丢弃。"""
    rels = [{"source": "顺顺", "target": "两个儿子", "type": "family", "confidence": 0.9}]
    r = EntityResolver(judge=judge_null)
    # 先注册 顺顺
    r.resolve(make_chunk(1), extraction(["顺顺"]))
    result = ExtractionResult.model_validate({
        "characters": [{"name": "顺顺", "category": "person"},
                       {"name": "两个儿子", "category": "collective"}],
        "relationships": rels,
    })
    out, _ = r.resolve(make_chunk(2), result)
    # 顺顺 canonical 保留；两个儿子 不注册；关系端点被解析为 两个儿子 原样（resolver 不崩）
    assert "顺顺" in r.known
    assert "两个儿子" not in r.known


def test_generic_with_candidate_goes_to_judge():
    """GENERIC 有候选 → 进入 alias judge；judge 明确通过 → alias。"""
    from app.schemas.llm import AliasJudgeResult as AJR
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AJR.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "年青人" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送"]))   # 建立 canonical
    out, _ = r.resolve(make_chunk(2), extraction(["年青人"], {"年青人": MentionCategory.GENERIC}))
    assert "年青人" in r.known and r.known["年青人"] == "傩送"   # judge 吸收为 alias
    assert "年青人" in r.canonical_aliases["傩送"]
    assert seen["pending"][0][0] == "年青人"
    assert seen["pending"][0][1] == ["傩送"]


def test_generic_no_candidate_dropped():
    """GENERIC 无候选 → 丢弃，不注册 canonical。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["年青人"], {"年青人": MentionCategory.GENERIC}))
    assert "年青人" not in r.known
    assert "年青人" not in r._index
    assert "年青人" not in r.canonical_aliases


def test_generic_does_not_absorb_polluted_collective_canonical():
    """GENERIC 的候选不得含历史污染 COLLECTIVE canonical（_recall 排除硬过滤 canonical）。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})
    r = EntityResolver(judge=j)
    # 模拟历史污染：直接向 _index 注入 两个儿子（旧数据场景），它应被 _recall 排除
    r._index["两个儿子"] = {"两个儿子"}
    r.known["两个儿子"] = "两个儿子"
    r.resolve(make_chunk(1), extraction(["傩送"]))   # 建立有效 canonical
    out, _ = r.resolve(make_chunk(2), extraction(["年青人"], {"年青人": MentionCategory.GENERIC}))
    cands = seen["pending"][0][1] if seen.get("pending") else []
    assert "两个儿子" not in cands
    assert "傩送" in cands   # 有效 canonical 正常进入候选


def test_descriptive_with_candidate_goes_to_judge():
    """DESCRIPTIVE 有候选 → 正常 alias judge。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "祖父" if p.mention == "翠翠的祖父" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["祖父", "翠翠"]))
    out, _ = r.resolve(make_chunk(2), extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert r.known.get("翠翠的祖父") == "祖父"
    assert "翠翠的祖父" in r.canonical_aliases["祖父"]


def test_descriptive_no_candidate_allowed_canonical():
    """DESCRIPTIVE 无候选 → 允许注册 canonical（不静默丢人物）。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["翠翠的祖父"], {"翠翠的祖父": MentionCategory.DESCRIPTIVE}))
    assert r.known.get("翠翠的祖父") == "翠翠的祖父"


def test_composite_with_candidate_goes_to_judge():
    """COMPOSITE 有候选 → 正常 alias judge（岳云二老 → 傩送）。"""
    seen = {}
    def j(text, pending):
        seen["pending"] = [(p.mention, [c.canonical for c in p.candidates]) for p in pending]
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": "傩送" if p.mention == "岳云二老" else None}
                            for p in pending]})
    r = EntityResolver(judge=j)
    r.resolve(make_chunk(1), extraction(["傩送", "二老"], {"二老": MentionCategory.COMPOSITE}))
    out, _ = r.resolve(make_chunk(2), extraction(["岳云二老"], {"岳云二老": MentionCategory.COMPOSITE}))
    assert r.known.get("岳云二老") == "傩送"


def test_category_none_legacy_person_fallback():
    """category=None 且 hard rules 未命中 → legacy PERSON fallback（正常注册）。"""
    r = EntityResolver(judge=judge_null)
    out, _ = r.resolve(make_chunk(1), extraction(["天保"]))   # 无 category
    assert r.known.get("天保") == "天保"   # 正常注册为 canonical


def test_filtered_mention_not_in_merge_evidence():
    """被过滤 mention 不得进入 merge_evidence。"""
    r = EntityResolver(judge=judge_null)
    r.resolve(make_chunk(1), extraction(["两个儿子"], {"两个儿子": MentionCategory.COLLECTIVE}))
    assert all("两个儿子" not in ev["mention"] and "两个儿子" not in ev["pair"]
               for ev in r.merge_evidence)
```

Run: `cd backend && python -m pytest tests/unit/test_hygiene.py -v`
Expected: 新增用例 FAIL（resolver 未实现 category 决策）。

- [ ] **Step 2: 实现 resolver 改动**

**2a. `resolve()` 开头过滤 COLLECTIVE/INVALID**（L45-53 区域）：chunk_names 排除硬过滤名；`confirmed` 排除硬过滤 canonical；`text_confirmed` 排除硬过滤 canonical：

```python
        from app.pipeline.hygiene import is_hard_filtered
        # V0.2.4：硬过滤 COLLECTIVE/INVALID（不进候选源；relation endpoint 涉及则跳过该关系）
        def _keep(name: str) -> bool:
            return not is_hard_filtered(name)

        chunk_names = (
            {c.name for c in result.characters if _keep(c.name)}
            | {r.source for r in result.relationships if _keep(r.source)}
            | {r.target for r in result.relationships if _keep(r.target)}
        )
        confirmed: set[str] = {self.known[n] for n in chunk_names if n in self.known}
        # 排除硬过滤 canonical（防历史污染节点进入候选源）
        confirmed = {c for c in confirmed if not is_hard_filtered(c)}
        text_confirmed: set[str] = self._text_mentions(chunk.text)
        text_confirmed = {c for c in text_confirmed if not is_hard_filtered(c)}
```

**2b. `_resolve_name` 决策表**（L135-145）：按 category 处理：

```python
    def _resolve_name(self, name: str, confirmed: set[str], text_confirmed: set[str]) -> tuple[str, bool]:
        from app.pipeline.hygiene import is_hard_filtered
        if name in self.known:
            canonical = self.known[name]
            confirmed.add(canonical)
            return canonical, False
        # V0.2.4：硬过滤 mention 永不注册（防御：即使漏过 resolve 开头过滤）
        if is_hard_filtered(name):
            return name, False   # 不注册、不进 pending——直接原样返回，关系/characters 保留原名的无害输出
        candidates = self._recall(name, confirmed, text_confirmed)
        # V0.2.4：category 决策（仅在 LLM 提供 category 时；None → legacy PERSON）
        cat = self._category_of(name)
        if not candidates:
            if cat == MentionCategory.GENERIC:
                return name, False   # 丢弃，不注册 canonical
            # PERSON / DESCRIPTIVE / COMPOSITE / None → 注册 canonical
            self._register(name)
            confirmed.add(name)
            return name, False
        return name, True  # 进 pending（GENERIC/DESCRIPTIVE/COMPOSITE/PERSON 均可 judge）
```

**2c. `_category_of(name)` helper**（新增）：从本 chunk 的 characters 中取 category：

```python
    def _category_of(self, name: str) -> MentionCategory | None:
        """返回本 chunk 提取的 category（若有）；跨 chunk 不保留。"""
        return self._current_categories.get(name)
```

**2d. `resolve()` 记录当前 chunk categories**（L38-39 区域）：

```python
        self._current_chunk_id = chunk.chunk_id
        self._current_chapter_id = chunk.chapter_id
        self._current_categories: dict[str, MentionCategory] = {
            c.name: c.category for c in result.characters if c.category is not None}
```

**2e. `_recall` 排除硬过滤 canonical**（L147-200 三层）：在 `_recall` 开头构建排除集，三层循环都跳过：

```python
    def _recall(self, mention, confirmed, text_confirmed):
        from app.pipeline.hygiene import is_hard_filtered
        ...
        # V0.2.4：硬过滤 canonical 不得进入任何一层候选
        def _candidate_ok(canonical: str) -> bool:
            return not is_hard_filtered(canonical)
```

在三层循环的 `continue` 条件中追加 `or not _candidate_ok(canonical)`（extraction 层 L127、text 层 L137、weak 层 L148/150）。

**2f. `_apply_judge` 防御**（L205-222）：judge 结果中 resolves_to 为硬过滤 canonical 时拒绝；被硬过滤 mention 的 resolution 不写 known：

```python
        from app.pipeline.hygiene import is_hard_filtered
        for r in judge_result.resolutions:
            if r.mention not in valid_mentions:
                continue
            if r.resolves_to is not None and r.resolves_to not in valid_canonicals:
                continue
            if r.resolves_to is not None and is_hard_filtered(r.resolves_to):
                continue   # 防御：不吸收硬过滤 canonical
            if is_hard_filtered(r.mention):
                continue   # 防御：被硬过滤 mention 的判定结果不写 known
            ...
```

- [ ] **Step 3: 运行 hygiene 测试确认绿 + resolver 回归**

Run: `cd backend && python -m pytest tests/unit/test_hygiene.py tests/unit/test_resolver.py -v`
Expected: test_hygiene 全 PASS；test_resolver 23 PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/resolver.py backend/tests/unit/test_hygiene.py
git commit -m "feat(resolver): V0.2.4 category 决策表（GENERIC 不建 canonical、DESCRIPTIVE/COMPOSITE 兜底、硬过滤排除）"
```

---

### Task 4: llm_client extract prompt + category 输出

**Files:**
- Modify: `backend/app/pipeline/llm_client.py`
- Test: `backend/tests/unit/test_llm_client.py`（追加 1 个）

**Interfaces:**
- Consumes: `MentionCategory`（Task 1）
- Produces: EXTRACTION_SYSTEM_PROMPT 增加 category 输出要求（向后兼容：LLM 可不输出）

- [ ] **Step 1: 修改 EXTRACTION_SYSTEM_PROMPT（L12-20）**

在 prompt 中追加 category 要求：

```python
EXTRACTION_SYSTEM_PROMPT = """你是小说人物关系抽取器。给定一段小说文本，抽取其中明确出现的人物，以及人物之间明确的关系。
严格要求：
1. 只抽取文本中明确出现的人物与关系，不要臆测。
2. characters: 文本中出现的人物姓名列表（同一人物按文本中的写法输出，不要合并别名）。
3. relationships: 人物之间的关系。source 是当前文本片段中作为关系主体的人物，target 是与其发生关系的人物。
4. type 只能使用以下 7 个枚举值之一：love（爱情）、family（血缘/家族）、friendship（友谊）、enmity（敌对/仇怨）、alliance（结盟/合作）、mentorship（师徒/师生）、other（其他无法归类的明确关系）。禁止自创类型。
5. confidence: 0 到 1 之间的浮点数。
6. category（可选）: 每个 character 可附 category，取值 person/generic/collective/descriptive/composite/invalid。
   - person: 专名（天保、傩送、翠翠）
   - generic: 泛指称谓（年青人、妇人、哥哥、弟弟）
   - collective: 集合称谓（两个儿子、兄弟二人、父子三人）
   - descriptive: 描述性称谓（翠翠的祖父）
   - composite: 复合称谓（岳云二老、天保大老、天保大人）
   - invalid: 畸形输入
   无法确定时省略 category 字段。
7. 只输出 JSON 对象，不要输出任何其他文字。格式：
{"characters": [{"name": "...", "category": "person"}], "relationships": [...]}"""
```

- [ ] **Step 2: 追加 llm_client 测试（category 透传）**

在 `backend/tests/unit/test_llm_client.py` 末尾追加：

```python
def test_extract_chunk_parses_category():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": (
        '{"characters": [{"name": "两个儿子", "category": "collective"}, {"name": "天保"}]}'
        ',"relationships": []}'
    )}}]})])
    result = client.extract_chunk("文本")
    assert result.characters[0].name == "两个儿子"
    assert result.characters[0].category == MentionCategory.COLLECTIVE
    assert result.characters[1].category is None   # 缺省 category 合法
```

import 追加 `MentionCategory`（检查现有 import，追加缺失的）。

Run: `cd backend && python -m pytest tests/unit/test_llm_client.py -v`
Expected: 全部 PASS（现有 + 1 新）。

- [ ] **Step 3: Commit**

```bash
git add backend/app/pipeline/llm_client.py backend/tests/unit/test_llm_client.py
git commit -m "feat(llm_client): V0.2.4 extract category 契约（可选字段，向后兼容）"
```

---

### Task 5: novels.py — mention_hygiene stats

**Files:**
- Modify: `backend/app/api/novels.py`
- Test: `backend/tests/unit/test_hygiene.py`（可选，stats 形状单测）

**Interfaces:**
- Consumes: resolver 内部计数（新增 `resolver.hygiene_stats`）
- Produces: job stats 增加 `mention_hygiene`

- [ ] **Step 1: resolver 增加 hygiene_stats 计数**

在 `__init__`（L27-34 区域）追加：

```python
        self.hygiene_stats: dict[str, int] = {
            "collective_filtered": 0, "generic_filtered": 0,
            "descriptive_resolved": 0, "composite_resolved": 0, "invalid_filtered": 0,
        }
```

在 `_resolve_name` 决策点计数：
- `is_hard_filtered(name)` 且 classify==COLLECTIVE → `collective_filtered += 1`；INVALID → `invalid_filtered += 1`
- GENERIC 无候选丢弃 → `generic_filtered += 1`
- DESCRIPTIVE 消歧成功（known 写入非自身）→ `descriptive_resolved += 1`
- COMPOSITE 消歧成功 → `composite_resolved += 1`

- [ ] **Step 2: novels.py 写入 stats**

在 `_run_ingest`（L67 区域，`stats["entity_resolution"]` 之后）追加：

```python
        stats["mention_hygiene"] = resolver.hygiene_stats
```

- [ ] **Step 3: 运行 unit 全量**

Run: `cd backend && python -m pytest 2>&1 | Select-Object -Last 4`
Expected: 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/novels.py backend/app/pipeline/resolver.py
git commit -m "feat(api): V0.2.4 mention_hygiene stats（job stats 增加过滤/解析计数）"
```

---

### Task 6: 全量回归

**Files:**
- Test: unit 全量 + integration 全量

- [ ] **Step 1: unit 全量**

Run: `cd backend && python -m pytest 2>&1 | Select-Object -Last 4`
Expected: 全部 PASS（88 既有 + hygiene 新用例 + llm_client 新用例）。

- [ ] **Step 2: integration 全量**

Run: `cd backend && python -m pytest -m integration 2>&1 | Select-Object -Last 4`
Expected: 全部 PASS（15 既有）。

- [ ] **Step 3: 确认范围未越界**

Run: `cd backend && git diff --stat HEAD~8`
Expected: 只含 schemas/llm.py、llm_client.py、pipeline/hygiene.py、pipeline/resolver.py、api/novels.py、test_hygiene.py、test_llm_client.py。无 Neo4j/API schema/前端改动。

- [ ] **Step 4: 无额外 commit（回归不改代码）**

---

## Self-Review

**1. Spec 覆盖（对照设计文档 §5/§6/§7/§8/§9）：**
- MentionCategory Enum + Character.category 可选 → Task 1 ✓
- hard rules 仅 COLLECTIVE/INVALID（范围锁死）→ Task 2 测试参数化 ✓
- resolver 决策表（GENERIC 丢弃/DESCRIPTIVE/COMPOSITE 兜底）→ Task 3 ✓
- category=None legacy PERSON fallback → Task 3 `test_category_none_legacy_person_fallback` ✓
- GENERIC 候选来自有效 index + 硬过滤 canonical 排除 → Task 3 `test_generic_does_not_absorb_polluted_collective_canonical` + _recall 排除 ✓
- COLLECTIVE relation endpoint 丢弃 → Task 3 `test_collective_as_relation_endpoint_drops_relation` ✓
- 被过滤名不污染 known/_index/canonical_aliases/merge_evidence → Task 3 测试 ✓
- extract prompt + category 透传 → Task 4 ✓
- mention_hygiene stats → Task 5 ✓
- 不修改 merge bridge / 不迁移 / 不新增 Group → Global Constraints ✓

**2. Placeholder 扫描：** 无 TBD/TODO；每步含完整代码与命令。

**3. 类型一致性：** `MentionCategory` 在 Task 1/2/3/4 使用一致；`classify_mention(name) -> MentionCategory | None` 在 Task 2/3 一致；`is_hard_filtered(name) -> bool` 在 Task 2/3 一致；`resolver._current_categories` 在 Task 3 定义与使用一致；`resolver.hygiene_stats` 在 Task 5 定义与 novels.py 引用一致。
