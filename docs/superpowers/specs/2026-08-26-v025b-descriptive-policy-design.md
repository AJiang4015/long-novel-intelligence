# V0.2.5-b：DESCRIPTIVE Canonical Policy（chunk 内 deferred + 单次 batch judge + unresolved 不注册）— 设计文档

- **日期**: 2026-08-26
- **版本**: V0.2.5-b（P17 专项）
- **状态**: 设计评审通过（决策锁定/修订 2026-08-26），**未实现**
- **前置**: V0.2.4 冻结（RC2/RC3）；V0.2.5-a（Context-aware ER）实现在前（非正文门控独立于本设计，但共用注册缝）

## 1. 背景与问题（P17）

真实《边城》评估（job `634f7f96`）：`大儿子` canonical（aliases=[], mc=1, ch=[5]）与 `天保` 分裂。补充证据：

- **ch5b 同 chunk 决定性事实**：ch5 切块 A=[0,4000) / B=[3600,4609)，实测偏移——两个小孩子@4063、顺顺@3820、大儿子@4439、第二个儿子@4458、长子@4477、天保@4481/4491、次子@4484、傩送@4488/4532——**全部在同一个 chunk B（约 100 字段落）内**。文本即写「他把长子取名天保，次子取名傩送」。
- 该 chunk 产出 6 个碎片节点：大儿子/长子/次子/第二个儿子（+天保/傩送 canonical）——**一族 6 碎片**；另 两个小孩子/两个年青人（RC2 覆盖面缺口，P09 follow-up，不在本设计范围）。
- 全书 61 节点中 45 个 mc=1 且单章；团总儿子模样的青年/宋家堡子里新嫁娘/牵羊的孩子/卖皮纸的过渡人/代理看船的/老朋友/老熟人 等瞬时描述全部成为 canonical。

## 2. 机制链

```
ch5b：confirmed 预扫描为空（全部首现）
→ characters 按 LLM 输出顺序逐个处理：
   先处理者（如 大儿子）: _recall 无候选 → 直接 _register（resolver.py:227-234）→ 绕过 judge 锁成 canonical
   后处理者（如 天保）: _index 已含 大儿子，chunk 原文含 "大儿子" 子串 → 候选=[大儿子] → judge
   → judge null → 天保 独立 canonical
→ 长子/次子/第二个儿子 依序各自注册 → 一族 6 碎片
→ 无桥接 mention → merge_evidence 无 (大儿子,天保) pair → merge judge 整体失败（109）→ 无从补救
```

**根因**：DESCRIPTIVE/COMPOSITE（甚至 PERSON）无候选时在「chunk 处理中途」立即注册 canonical，早于看到完整 chunk——**canonical 创建存在 chunk 内顺序竞态**（P10 家族在 canonical 注册层的复发）。先处理者绕过 judge；后处理者才拿到候选。大儿子↔天保 分裂**不是** zero-overlap 召回失败（P08），而是**同 chunk 首现顺序问题**。

## 3. 锁定决策（评审 2026-08-26，含修订）

- **D1（范围）**：采用 **B1 = chunk 内 deferred**；跨 chunk / 跨章 deferred = **B2 后续独立能力，本轮不实现**。
- **D2（unresolved 语义）**：deferred mention 在以下四路均 → **unresolved**：① chunk 末重召回仍无候选；② judge null；③ judge 结果缺失该 mention；④ judge 异常。unresolved = 不注册 canonical、不进 known/_index/canonical_aliases/merge_evidence、从 chunk 输出剔除、以之为端点的关系丢弃、计入 stats。**修订点：取代既有「DESCRIPTIVE 无候选 → 注册 canonical（不静默丢人物）」兜底**（P009 trade-off 的**有意取代**，非回归）。
- **D3（单次 batch judge，澄清）**：**pending（处理期有候选）+ deferred 重召回 的全部 mention–candidate pairs 合并为同一次 `self._judge(chunk.text, pending_all)` 调用**，`_apply_judge` 统一应用；**零额外 LLM 请求**。不得拆成两次 judge。
- **D4（judge 异常，澄清）**：**异常时 deferred 永不 canonicalize**——异常路径按 category 分派：PERSON/category=None → 兜底注册（既有 fail-safe 保留）；GENERIC → 丢弃（与 RC3「GENERIC 永不 canonical」对齐，**顺带修复既有 exception 路径会把 GENERIC pending 注册成 canonical 的洞**，标记评审）；DESCRIPTIVE/COMPOSITE（含 deferred 重召回后并入 pending 者）→ **unresolved**。fail-safe 与 unresolved 决策无冲突。
- **D5（覆盖缺口，正式声明）**：**category=None → legacy PERSON fallback → B1 不生效**——LLM 未输出 category 的描述性 mention 仍按 PERSON 立即注册。列为 **P017 Known Limitation / P06 follow-up**；**本轮不引入确定性 classifier**（任何补充分类器需另立设计）。

## 4. 状态机（精确）

```
# —— chunk 处理期 ——
pending: list[PendingMention] = []   # 有候选（PERSON/DESCRIPTIVE/COMPOSITE/GENERIC）
deferred: list[str] = []             # DESCRIPTIVE/COMPOSITE 无候选
unresolved: set[str] = set()         # 最终不注册集合

characters/relationships 处理（现有逻辑 + 分支）：
  PERSON / None 无候选        → 立即 _register（不变）
  GENERIC 无候选              → 丢弃（RC3 不变）
  DESCRIPTIVE/COMPOSITE 有候选 → pending.append（不变）
  DESCRIPTIVE/COMPOSITE 无候选 → deferred.append（不注册）

# —— chunk 末：deferred 重召回（此刻本 chunk 新 canonical 已在 _index）——
# ⚠️ 明确（评审 2026-08-26）：此处的 confirmed / text_confirmed 必须是——
#   ① 完成当前 chunk 全部正常 character 处理之后、已包含本 chunk 新增正式 canonical 的候选集合；
#   ② 绝不能包含 provisional（provisional 始终排除出候选源，T-a14 语义在 -b 同样成立）。
#   实现者不得直接复用处理期旧变量——否则 B1 将看不到 大儿子/长子/天保/傩送 之间
#   刚建立的局部候选关系，顺序无关性（T-b1/T-b2）失效。
for m in deferred:
    cands = self._recall(m, confirmed, text_confirmed)   # confirmed/text_confirmed 已含本 chunk 新增正式 canonical
    if cands: pending.append(PendingMention(mention=m, candidates=cands))   # 并入同一批
    else:     unresolved.add(m)                                              # ① 无候选

# —— 单次 batch judge（D3）——
if pending:
    try:
        judge_result = self._judge(chunk.text, pending)      # 一次调用，含全部 candidate pairs
        self._apply_judge(judge_result, pending)             # 统一应用：
            # resolves_to 有效 → alias（既有语义）
            # null / 缺失：
            #   PERSON / None → _register（既有）
            #   GENERIC       → 丢弃（RC3）
            #   DESCRIPTIVE/COMPOSITE → unresolved（②③）
    except Exception:                                        # ④ 异常（D4）
        for p in pending:
            cat = category_of(p.mention)
            if cat in (PERSON, None): self._register(p.mention)   # 既有 fail-safe（仅 PERSON/None）
            elif cat == GENERIC:     continue                     # 丢弃（与 RC3 对齐）
            else:                    unresolved.add(p.mention)    # DESCRIPTIVE/COMPOSITE → unresolved
        failed = True

# —— 输出剔除 ——
dropped = unresolved ∪ (GENERIC 判 null 丢弃，沿用现有机制)
resolved_chars / resolved_rels 移除 dropped；端点命中 dropped 的关系丢弃
stats: descriptive_unresolved / composite_unresolved（+ 既有 descriptive_resolved / composite_resolved）
```

## 5. 与既有代码的最小 diff 语义

1. `_resolve_name` 无候选分支：DESCRIPTIVE/COMPOSITE → 返回 deferred 标记（不 `_register`）；PERSON/None 不变。
2. `resolve()`：收集 deferred → chunk 末重召回 → 并入 pending → 单次 judge。
3. `_apply_judge`：null/缺失 分支按 category 分派（DESCRIPTIVE/COMPOSITE → unresolved，不注册）。
4. 异常路径：category 分派（见 D4）。
5. 输出剔除：`dropped = unresolved ∪ generic_dropped`。
6. stats 扩展两个计数器。

**不改**：llm_client（judge 契约/prompt）、merger、hygiene.py（词表/硬过滤）、extract prompt、merge bridge、Neo4j schema、并发/超时。

## 6. 测试矩阵（全 deterministic，mock judge，双 extraction 顺序）

| ID | 用例 | 期望 |
|---|---|---|
| T-b1 | 大儿子+天保 同 chunk，大儿子 先出现 | 末批重召回 → 并入单次 judge（mock 确认）→ 大儿子 alias 天保 |
| T-b2 | 同 chunk，天保 先出现 | 最终 canonical 集合与 T-b1 一致（**顺序无关**） |
| T-b3 | ch5b 段落夹具（一族 6 名） | judge-agree mock → 收敛 ≤2 canonical |
| T-b4 | DESCRIPTIVE chunk 末仍无候选 | **unresolved：不注册、输出剔除、计数** |
| T-b5 | DESCRIPTIVE judge null | **unresolved：不注册** |
| T-b6 | DESCRIPTIVE 缺席 judge 结果 | **unresolved：不注册** |
| T-b7 | judge 异常 | pending PERSON 兜底注册；deferred（及并入 pending 的 DESCRIPTIVE/COMPOSITE）→ **unresolved，永不 canonicalize**；GENERIC → 丢弃 |
| T-b8 | 翠翠的祖父 有候选 祖父 | alias 路径不变（回归） |
| T-b9 | 天保大老 / 岳云二老 有候选 | bridge judge 不变（回归） |
| T-b10 | GENERIC 回归 | RC3 不变 |
| T-b11 | **零额外 LLM 调用** | 断言每 chunk judge 仅调用 1 次（pending+deferred 同批） |
| T-b12 | unresolved 端点关系 | 关系丢弃 |
| T-b13 | PERSON 无候选 | 立即注册（锁死，回归） |
| T-b14 | unresolved 不入 merge_evidence | merge_evidence 无相关 mention/pair |

## 7. 回归与测试适配

- **`test_hygiene.py:176 test_descriptive_no_candidate_allowed_canonical` 修订**：改为断言 DESCRIPTIVE 无候选 → unresolved（不注册、不进 known、输出剔除）——**有意的行为变更**（D2），非回归。
- 其余现有测试不变（`test_descriptive_with_candidate_goes_to_judge`、`test_composite_with_candidate_goes_to_judge`、`test_category_none_legacy_person_fallback` 等均保持）。
- 全量回归：hygiene 59 / resolver+merger+llm_client 124 / unit 148 / integration 15。

## 8. 不变量 / Do Not Do

- 翠翠的祖父 / 天保大老 / 岳云二老（有候选）路径零变化；GENERIC/硬过滤/merge bridge/judge 契约零变化；PERSON 无候选注册锁死。
- 不把 DESCRIPTIVE 全部 hard filter；不把 大儿子/长子/次子 加入词表；不引入跨 chunk buffer（B2 后续）；不引入 classifier（D5）。
- judge 每 chunk 至多一次（成本不变）。

## 9. 真实评估验收指标（下一次《边城》）

- **DESCRIPTIVE：resolved / unresolved / canonical 数量**（期望：unresolved>0、descriptive canonical 显著下降；resolved 与既有 alias 能力保持）。
- **ch5b 一族**：大儿子/长子/次子/第二个儿子 → 是否收敛到 天保/傩送（期望 ≤2 canonical；judge 配合下；P06 方差以趋势判定）。
- **merge_evidence / merge 观察**：一族碎片消失后，merge candidate pairs 构成是否更干净（配合 P08 INCONCLUSIVE 复验）。
- 与 P16-a 指标（非正文 canonical、provisional promoted/dropped、父亲 first_seen）合并出具；`顺顺→父亲` 若仍发生属 P16-b 观察，不判 -a/-b 失败。
