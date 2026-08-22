# V0.2.3-a Candidate Ranking 修正（强信号永不挤掉）— 设计文档

- **日期**: 2026-08-23
- **版本**: V0.2.3-a
- **状态**: 已批准（设计评审通过，待实现）
- **范围**: `backend/app/pipeline/resolver.py` + `backend/tests/unit/test_resolver.py`
- **明确不改**: judge、canonical merge、extraction、Neo4j、API、frontend

## 1. 背景与问题

V0.2.2 三层候选召回（extraction 共现 → 文本层共现 → 字符重合/子串）中，最终 `return out[:RECALL_TOP_K]` 的总截断对**强信号同样生效**。重放证据（`.tmp/replay_v022.txt` chunk 11）：`天保大老` 的候选为 `[顺顺,兄弟,祖父,翠翠,小的]`，text confirmed 命中的 `天保`（子串命中 canonical）排第 6 被截断——因为该 chunk 的 extraction confirmed 恰好占满 5 个。

结果：强信号可能被弱信号 Top-K 挤掉，`天保大老` 的候选不一定包含 `天保`（A 组）与 `大老`（B 组），judge 无从合并。

## 2. 目标

> 强信号永远不被弱信号 Top-K 挤掉。

先确保：`天保大老` → candidates 一定包含 `天保`、`大老`。

## 3. 设计

### 3.1 候选分级与容量规则

`_recall` 重构为两段式：

| 层级 | 来源 | 容量 |
|---|---|---|
| strong | extraction confirmed + text confirmed | 按 canonical 去重后**全部保留**，不受 `RECALL_TOP_K` 限制 |
| weak | character overlap / substring | 内部去重排序，**只补足**到 `RECALL_TOP_K` |

**最终公式**：

```python
final_candidates = strong_candidates + weak_candidates[:max(0, RECALL_TOP_K - len(strong_candidates))]
```

行为示例：

- strong=3 → weak 最多 2，final=5
- strong=5 → weak=0，final=5
- strong=7 → 全部 strong 保留，weak=0，final=7

**`RECALL_TOP_K` 语义变更**：从「最终候选数硬上限」改为「weak candidate 的补位目标容量」。

### 3.2 strong 内部顺序

保持现有：extraction confirmed 在前，text confirmed 在后。

### 3.3 去重

保持 canonical 级去重（同一 canonical 只出现一次）；strong 与 weak 之间也去重（weak 排除已在 strong 中的 canonical）。

## 4. 代码改动（resolver.py）

仅改 `_recall`（约 L114-164）：

```python
def _recall(self, mention, confirmed, text_confirmed) -> list[AliasCandidate]:
    out: list[AliasCandidate] = []
    seen: set[str] = set()

    # 1) strong：extraction 共现（现有优先级在前）
    for canonical in confirmed:
        if canonical == mention or canonical not in self._index or canonical in seen:
            continue
        seen.add(canonical)
        out.append(AliasCandidate(canonical=canonical, matched_names=sorted(self._index[canonical])))

    # 2) strong：文本层共现（现有顺序在后）
    for canonical in text_confirmed:
        if canonical == mention or canonical not in self._index or canonical in seen:
            continue
        seen.add(canonical)
        out.append(AliasCandidate(canonical=canonical, matched_names=sorted(self._index[canonical])))

    # 3) weak：字符重合/子串，只补足到 RECALL_TOP_K（strong 不参与截断）
    scored: list[tuple[int, int, str]] = []
    for canonical, names in self._index.items():
        if canonical in seen:
            continue
        hit = None
        for n in names:
            if mention in n or n in mention:
                hit = n
                break
        overlap = max(_overlap(mention, n) for n in names) if names else 0
        scored.append((1 if hit else 0, overlap, canonical))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    for _prio, _ov, canonical in scored[: max(0, RECALL_TOP_K - len(out))]:
        seen.add(canonical)
        out.append(AliasCandidate(canonical=canonical, matched_names=sorted(self._index[canonical])))
    return out  # 不再 out[:RECALL_TOP_K] 截断 strong
```

`RECALL_TOP_K` 常量值不变（仍 5），docstring 注释同步更新语义。

## 5. 测试改动（test_resolver.py）

### 5.1 新增用例

新增 3 个容量测试：

1. `test_strong_3_weak_fills_to_5`：strong=3（extraction 2 + text 1）→ 最终 5，weak 补 2 个
2. `test_strong_5_no_weak`：strong=5 → weak 不补，最终 5
3. `test_strong_7_not_truncated`：strong=7 → 7 个全部保留，不截断

去重场景复用现有 `test_text_and_extraction_cooccurrence_dedup`（同 canonical 只出现一次）。

### 5.2 现有测试影响

| 现有测试 | 影响 | 处理 |
|---|---|---|
| `test_text_candidates_priority_and_topk_merge`（L281） | strong 仅 2 个，weak 补 3 个 → 仍 ≤5 | 不改 |
| `test_text_no_known_names_no_text_candidates`（L256） | strong 空 → weak 补满 5，`cands[0][0]=="大老"` 不变 | 不改 |
| `test_text_cooccurrence_adds_canonical_absent_from_characters`（L232） | `cands[0][0]=="傩送"` 不变 | 不改 |
| 其余共现/顺序测试 | 均不触及 strong>5 场景 | 不改 |

预期现有 19 个测试全部保持通过。

## 6. 验证

1. 新增 3 个容量测试通过
2. 现有 test_resolver.py 全部通过
3. 集成测试回归（13 项）
4. 重放验证：`天保大老` 候选包含 `天保` 与 `大老`（可选，需真实 LLM）

## 7. 不变量

- strong（extraction + text confirmed）永不因 weak 排名/数量被截断
- canonical 级去重保持
- extraction 在 text 前的 strong 内部顺序保持
- judge 契约、canonical merge、Neo4j 行为不变

## 8. 已知限制 / 后续

- 本改动只保证「候选完整」，不实现跨 canonical 合并（P08 根治方向仍待 V0.2.3-b）
- 极端情况 strong 数量多时 judge prompt 变长（实际 chunk 内已知 canonical 数量有限，可接受）

## 9. 明确不做（YAGNI）

- 不改 judge prompt / 契约
- 不做 canonical merge / bridge propagation
- 不调整 RECALL_TOP_K 数值
- 不改 extraction、Neo4j、API、frontend
