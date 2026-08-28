# P20 Design Spec — Evaluation Framework（人工 Neo4j 验收 → 可重复 regression evaluation）

- **日期**: 2026-08-28
- **版本**: v1.1（Review Round 1 三项阻断修订已合入；待复审）
- **状态**: Review Round 1 修订完成（2026-08-28，三项阻断修订合入 v1.1）→ 待复审后进入实现
- **前置**: [P020 Problem Record](../problems/P020-evaluation-framework.md)（Evidence 已收集、边界已定）；PROCESS.md §5 准入
- **约束（用户指定，锁定）**:
  1. **不修改 P19 checkpoint 语义**：checkpoint store / 编排 / 指纹零改动；eval 以既有开关 `er_checkpoint_enabled=False` 运行（强制 fresh novel）；
  2. **不重开 P16/P17/P18 决策**：D-5 / D-6 / D-9 / D-10 / D-13 / D-17 冻结语义**编码进检查集**，已知限制与冻结残留必须判 OBSERVATION，不得以 FAIL 形式重开；
  3. **不进入性能优化**：无计时门禁、无 profiling 交付物；耗时仅作观察记录（P19 已 profiling，不重复）；
  4. **先建立质量基线**：P20 阶段一交付物 = 基线本体（N≥3 真实运行冻结基线 artifact）；基线暴露的质量问题只记录为 observation / 新立项，**不在 P20 修复**。

---

## 0. 修订记录

### v1.1（2026-08-28，Review Round 1 三项阻断修订）

| # | 阻断项 | v1.1 修订 |
|---|---|---|
| 1 | stable/variance 定义错误：「pass-rate=1.0 → stable」会把稳定失败误判为 variance | 改为**决定性结果稳定性分类**（§4.3）：全部 PASS → stable；全部 FAIL → **stable（stable failure）**；PASS/FAIL 混合 → variance；**stable/variance 描述结果稳定性，不描述 correctness**；「是否满足 expected」在分类之后单独判定（§5.2 `satisfies_expected`） |
| 2 | compare 以 git_commit 作拒绝条件，阻断了回归比较的正常场景（不同 commit vs 历史基线） | git_commit / git_dirty 仅作 **provenance**（记录不判定）；compare 兼容性由 **compare_identity**（语义身份：corpus_hash + checkset_version + model + chunk_size + chunk_overlap + chunker_version + extractor_version + prompt_hashes×3）判定；**不兼容才 REFUSE_COMPARE**（§5.2 / §7.1） |
| 3 | 稳定失败可被冻结为「正常 baseline」 | 新增 **baseline validity**（§7.3）：stable 检查 FAIL/FAIL/FAIL → 事实照存（outcome_distribution + stable_failures）但 `baseline_status = INVALID_NOT_REGRESSION_SAFE`，**禁止用于对未来运行做正常 REGRESSION 判定**（REFUSE_COMPARE）；variance 检查正常保存 outcome distribution；仅 VALID 基线可作为 regression baseline |

### v1（2026-08-28 初稿）

- 初版设计（checkset / run / baseline / compare / evidence dump / 报告 / 测试矩阵 / 实施顺序）。v1 的「pass-rate=1.0 → stable」「git_commit 作 compare 拒绝条件」「无基线有效性」经 Review Round 1 评审被修订（见上表），不作为现行语义。

---

## 1. 背景与目标

### 1.1 问题

真实 ER 验收全链人工：上传固定语料 → 等待 job → Cypher 查询（TESTING.md §5）→ 人工对照 TESTING.md §4 基线期望与 §9.1 版本化指标 → 人工翻原文做 aliases 可解释性核对（P18 纪律）→ 手写报告。检查定义只有散文形态、执行只有人工形态 → 单次运行不结论（P06）、无冻结基线、回归不可比、人工成本高（每次 30-90 分钟）。

### 1.2 目标

1. **一键可重复**：`python -u tools/eval_framework/run.py --runs N` 产出结构化 `result.json` + 自动 markdown 报告（TESTING.md §9 模板 + 强制声明）；
2. **检查集可执行化**：TESTING.md §4/§9.1 + P16/P17/P18 验收 → 声明式、版本化、带归因（D-XX/PXX + 归因链 layer）的 checkset；
3. **趋势与稳定性感知**：N 运行聚合 per-check outcome_distribution + pass-rate；stable/variance 按**结果稳定性**分类（§4.3，P06 纪律：多次取趋势）；
4. **质量基线**：首次 N≥3 运行冻结基线 artifact（`docs/evaluation/baselines/`）；未来运行与基线比较 → REGRESSION / 观察波动；
5. **人工部分收敛**：aliases 语义可解释性核对从「翻书」变为「复核 evidence dump」（自动产证据、人工下结论）。

---

## 2. 现状人工验收流程（代码/文档事实，2026-08-28）

```text
人工验收链（每次真实评估）：
1. 上传 books/边城_….epub（固定语料）→ 等待 job 终态（真实 LLM）
2. 记录 Environment Baseline（TESTING.md §6：commit/model/chunk/overlap/concurrency/novel_id/Neo4j）
3. Cypher 查询（TESTING.md §5 三段：persons 表 / relationships 计数 / alias 搜索）
4. 人工对照 TESTING.md §4 基线（傩送/二老、天保/大老、老船夫/爷爷/老人、负向）
   + §9.1 版本化指标（非正文 canonical / provisional / DESCRIPTIVE / ch5b / P18 sink）
5. 人工翻原文核对 aliases 可解释性（P18 Do Not Reopen 纪律）
6. 手写 markdown 报告（TESTING.md §9 模板 + 强制声明）
```

**已可复用的脚本化骨架（P19 评估实证）**：`tools/eval_p19_resume.py` 已实现「TestClient 上传 → 轮询 job → Neo4j 稳定键快照 → LLM 调用计数 → result.json + stdout 摘要」。P20 在其上扩展检查/基线/报告，不重造轮子。

**现有可复用件**：
- `config.er_checkpoint_enabled`（`ER_CHECKPOINT_ENABLED`，默认 True）→ eval 设 False 即回退 pre-P19 行为、每上传全新 novel_id（TESTING.md §3 fresh-novel 纪律）；
- `test_api_neo4j.py:145` 的 `app.state.llm_client = FakeLLMClient()` 注入模式 → harness 可选 `--smoke`（mock LLM + 真实 Neo4j）自检骨架；
- `diagnose_lineage.py` + `ER_LINEAGE=1`（D-8 observer）→ evidence dump 可选的 judge 事件补充。

---

## 3. 核心概念与职责分层（钉死）

| 概念 | 职责 | 生命周期/位置 |
|---|---|---|
| **checkset** | 声明式检查定义（期望 / 分类 / 归因 / 前置），编码 TESTING.md §4/§9.1 + P16/P17/P18 冻结语义 | 版本化（`checkset_version`）；修改期望 = 修改决策（独立立项） |
| **run** | 一次真实 ingest（fresh novel）+ Neo4j 快照 + 执行 checkset → `result.json` | 每次独立；`{eval_workdir}/runs/{run_id}/` |
| **baseline** | N 运行聚合（per-check outcome_distribution / §4.3 stable-variance 分类 / satisfies_expected / baseline_status）→ 冻结 artifact | durable；`docs/evaluation/baselines/` |
| **compare** | 单次运行 vs 基线 → REGRESSION / 观察波动 / INCONCLUSIVE | 读取基线 + 运行结果 |
| **evidence dump** | alias→原文上下文（确定性检索，零 LLM）供人工复核 | run 产物；人工复核结论回填 `annotation` |
| **report** | TESTING.md §9 模板 markdown（自动生成） | run/基线产物 |

**位置与依赖方向**：`backend/tools/eval_framework/`（工具层，与 `diagnose_lineage.py` / `eval_p19_resume.py` 同级；**非 app 层**，不进 ARCHITECTURE.md 层表）。

```text
eval_framework ──▶ app（create_app / pipeline.chunker / db）── 经 TestClient（同 eval_p19_resume）
                ──▶ 不 import checkpoint（eval 禁用 checkpoint；守卫断言 G5）
                ──▶ 只读 Neo4j（自建 novel_id）+ 只写自身工作目录（.tmp/eval-framework/，gitignored）
```

---

## 4. 检查集（checkset v1）

### 4.1 检查定义 schema

```json
{
  "schema_version": 1,
  "checkset_version": "1",
  "corpus": {
    "name": "边城",
    "path": "books/边城_(沈从文)_(z-library.sk,_1lib.sk,_z-lib.sk).epub",
    "content_hash": "<sha256>"
  },
  "applies_to": "V0.2.5+（冻结语义集）",
  "checks": [
    {
      "id": "A1",
      "group": "正向合并",
      "description": "傩送/二老/老二 归并为同一 canonical，aliases 含其余名",
      "preconditions": ["person_exists(傩送) or person_exists(二老)"],
      "expectation": {
        "kind": "single_canonical_with_aliases",
        "members": ["傩送", "二老", "老二"],
        "alias_contains": ["二老"]
      },
      "outcome_class": "variance",
      "attribution": "P08 / D-4",
      "layer": "merge",
      "severity": "normal"
    }
  ]
}
```

- **前置条件（防空洞 PASS）**：如 C1「父亲 非 Person」必须前置「顺顺 存在」——否则「父亲 未提取」也会 trivially PASS；前置不满足 → `SKIP`（标注原因），**不计 PASS**；
- **outcome_class 初判**：stable（机制确定性期望）/ variance（P06 波动期望）；**基线运行按 §4.3 经验重新分类**（v1.1：按决定性结果稳定性，非 pass-rate）；
- **attribution / layer**：每条检查声明归属（D-XX / PXX / 冻结决策）与归因链层（PIPELINE_LAYER §4：extraction / recall / judge / admission / registration / merge）——FAIL 时按此路由到拥有该决策的层。

### 4.2 检查清单 v1（分组 A-G）

| id | 检查 | 期望 | 初判 | 归因 / layer |
|---|---|---|---|---|
| **A 正向合并（TESTING.md §4）** | | | | |
| A1 | 傩送 / 二老 / 老二 → 单 canonical，aliases 含其余名 | 合并 | variance | P08 / D-4 / merge |
| A2 | 天保 / 大老 → 单 canonical | 合并 | variance | P08 / D-4 / merge |
| A3 | 老船夫 无独立 canonical，∈ 祖父.aliases | 合并 | stable | P08 / D-4 / merge |
| A4 | 爷爷 → 祖父 alias | 合并 | variance（V0.2.6 曾独立 Person） | P06 / judge |
| A5 | 负向：傩送 vs 杨马兵 不同 canonical（不合并） | 不合并 | stable | P08 / D-4 / merge |
| A6 | alias 搜索：`GET /api/novels/{id}/characters?q=二老` → 唯一命中 name=傩送 | 唯一 canonical | variance | D-2 / registration |
| **B 非正文（V0.2.5-a，P016）** | | | | |
| B1 | 非正文 canonical 数量 == 0 | 0 | stable | P016 / admission |
| B2 | provisional → promoted / dropped 计数 | 记录（observation） | — | P016 / admission |
| **C P16-b / P18 冻结（D-5 / D-6）** | | | | |
| C1 | `父亲` 非 Person 且无任何 canonical aliases 含它（前置：顺顺 存在） | 拦截 | stable | D-5 / D-6 / admission |
| C2 | `翠翠的父亲` 不在任何 aliases（前置：翠翠 或 翠翠的父亲 被提取） | 拦截 | stable | D-5 / admission |
| C3 | `爹爹` ∈ 顺顺.aliases（≥2 独立证据 → confirmed） | confirmed | variance（V0.2.6 实证） | D-5 / admission |
| C4 | 顺顺.aliases 不含 `父亲` / `爸爸`（sink 收敛；爸爸 波动归 D5） | 收敛 | variance | D-6 / P018 / admission |
| C5 | `爸爸` 独立 Person → **OBSERVATION**（D5 Known Limitation，非 FAIL） | 观察 | — | D-10 / P017-D5 / registration |
| **D P17 / D-9** | | | | |
| D1 | 大儿子 / 长子 / 次子 家族收敛（不碎片为独立 canonical） | 收敛 | variance | P017 / D-9 / registration |
| D2 | descriptive_resolved / unresolved 计数 | 记录（observation；趋势） | — | P017 / P06 |
| D3 | 无候选 DESCRIPTIVE → 不注册（D-9 invariant；stats + 图缺位联合判定） | 不注册 | stable | D-9 / registration |
| **E P09 hygiene** | | | | |
| E1 | collective / generic 过滤计数 | 记录（observation；趋势） | — | P09 / hygiene |
| **F merge** | | | | |
| F1 | merge_stats 记录；全部 failed → **INCONCLUSIVE**（非 FAIL） | 记录 | — | P11 / merge 域 |
| **G 数据安全与图完整性** | | | | |
| G1 | 本 novel 子图 labels ⊆ {Novel, Person}（RELATES_TO 为关系） | 隔离 | stable | D-3 / db |
| G2 | persons / relationships 计数 | 记录 | — | — |
| G3 | 无跨 novel 污染（仅自身 novel_id 查询） | 隔离 | stable | D-2 / D-3 / db |
| G4 | failed_blocks 记录；失败 chunk 覆盖的检查 → 自动降级 SKIP/INCONCLUSIVE 并标注 | 降级 | — | P04/P05/P13 |
| G5 | run 后断言：该 novel 无 checkpoint 目录产生（P19 未被触碰的守卫） | 零接触 | stable | P19（约束 1） |

> **语义边界（关键）**：C5 / D2 / E1 / F1 / B2 是 OBSERVATION 类检查——**记录不判败**，编码「已知限制 / 冻结残留 / 无法判定」的既有语义（AGENTS.md §3 红线：不因「爸爸 未 confirmed」「翠翠的祖父 未建立」判失败）。任何把 OBSERVATION 改判 FAIL 的诉求 = 修改决策，需独立立项/解除冻结。

### 4.3 stable / variance 经验分类（v1.1，阻断项 1）

> **stable/variance 描述结果稳定性，不描述 correctness。**

以基线 N 次运行中该检查的**决定性结果**（PASS / FAIL；INCONCLUSIVE / SKIP 不参与）为输入：

| 决定性结果分布 | 分类 | 含义 |
|---|---|---|
| 全部 PASS | **stable（符合 expected）** | 结果确定性满足期望 |
| 全部 FAIL | **stable（stable failure）** | 结果确定性违反期望——**是稳定失败，不是 variance** |
| PASS 与 FAIL 混合 | **variance** | 结果随 LLM 非确定性波动（P06） |
| 决定性结果 < 2 次 | UNCLASSIFIED | 样本不足；保守按 variance 处理（不宣称 stable） |

- **稳定 ≠ 正确**：分类只回答「结果是否稳定」；「是否满足 expected」在分类之后**单独判定**（§5.2 `satisfies_expected`）；
- stable 且全部 PASS → 满足 expected；stable 且全部 FAIL → **stable failure**（基线有效性受影响，见 §7.3）；variance → 保存 outcome distribution 与 pass-rate（趋势信号，单次不构成回归证据）；
- 基线运行后按本规则**经验重分类**，覆盖 checkset 中 outcome_class 初判（初判只作为先验）。

---

## 5. 数据模型

### 5.1 run result.json

```json
{
  "schema_version": 1,
  "run_id": "uuid",
  "timestamp": "...",
  "env": {
    "git_commit": "...", "git_dirty": false,
    "model": "...", "chunk_size": 4000, "chunk_overlap": 400, "concurrency": 4,
    "neo4j_version": "...", "novel_id": "...", "checkpoint_enabled": false
  },
  "corpus": { "name": "边城", "content_hash": "..." },
  "job": { "job_id": "...", "status": "...", "failed_blocks": [], "stats": {...} },
  "graph_snapshot": { "persons": [...], "relationships": [...], "counts": {...} },
  "checks": [ { "id": "A1", "outcome": "PASS", "actual": "...", "evidence": "..." } ],
  "evidence_dump": { "persons": [ { "canonical": "顺顺", "aliases": [...],
                                     "alias_contexts": [ { "alias": "爹爹", "chunk_id": 14, "chapter_id": 13,
                                                           "snippet": "…应当由大老爹爹作主…" } ] } ] },
  "annotations": [ { "check_id": "C4", "reviewer_note": "顺顺 aliases 逐条可解释（人工复核）" } ],
  "warnings": []
}
```

- **graph_snapshot 稳定键**：复用 P19 AC-2 canonical serialization 思路——persons 按 name 排序（aliases 保序、chapters/chunk_ids 排序），relationships 按 (source,target,type) 排序；**不使用 uuid id**；
- **env 字段 = TESTING.md §6 必填**：缺失任一 → run refuse（见 §6.1）。

### 5.2 baseline artifact（`docs/evaluation/baselines/`）

```json
{
  "schema_version": 1,
  "baseline_id": "biancheng-v0.2.9-2026-08-28",
  "created": "...",
  "runs": [ "run_id_1", "run_id_2", "run_id_3" ],
  "provenance": { "git_commit": "...", "git_dirty": false, "model": "...", "concurrency": 4, "neo4j_version": "..." },
  "compare_identity": {
    "corpus_hash": "...", "checkset_version": "1",
    "model": "...", "chunk_size": 4000, "chunk_overlap": 400,
    "chunker_version": "1", "extractor_version": "1",
    "prompt_hashes": { "extraction": "...", "judge": "...", "merge": "..." }
  },
  "baseline_status": "VALID | INVALID_NOT_REGRESSION_SAFE",
  "stable_failures": [ { "check_id": "C1", "outcome_distribution": { "PASS": 0, "FAIL": 3 } } ],
  "per_check": {
    "A1": { "stable": true, "satisfies_expected": true,
            "outcome_distribution": { "PASS": 3, "FAIL": 0, "OBSERVATION": 0, "INCONCLUSIVE": 0, "SKIP": 0 } }
  },
  "quality": { "stable_check_count": 6, "stable_failure_count": 0, "variance_checks": ["A1","A4","C3","C4","D1"], "notes": [...] }
}
```

- **经验分类（v1.1，§4.3）**：决定性结果全同 → stable（含 stable failure）；混合 → variance；决定性结果 < 2 次 → UNCLASSIFIED（保守按 variance）；
- **satisfies_expected（v1.1）**：stable 检查在分类后**单独判定**是否满足 expected——全部 PASS → true；全部 FAIL → false（**stable failure**）；
- **baseline_status（v1.1，阻断项 3）**：不存在 stable failure（全部 stable 检查 satisfies_expected=true）→ `VALID`；存在 → `INVALID_NOT_REGRESSION_SAFE`——**事实照存，但禁止作为 regression baseline**（§7.3；compare → REFUSE_COMPARE）；
- **compare_identity（v1.1，阻断项 2）**：compare 兼容性唯一判定依据 = **语义身份**（corpus_hash + checkset_version + model + chunk_size + chunk_overlap + chunker_version + extractor_version + prompt_hashes×3）；**git_commit / git_dirty 仅为 provenance（记录，不参与判定）**——回归比较的正常场景就是不同 commit 与历史基线比较；未来新增的任何 pipeline/schema 语义版本常量一律加入 compare_identity（与 P19 config_fingerprint「语义相关才作废」同哲学）。

### 5.3 工作目录

`backend/.tmp/eval-framework/`（gitignored，同 lineage-tests 约定）：`runs/{run_id}/result.json`、`runs/{run_id}/report.md`、`baselines/`（copy）。**durable 产物**（基线 artifact + 基线报告）落 `docs/evaluation/baselines/`。

---

## 6. 运行流程

### 6.1 `run.py`（cli：`--runs N --tag <tag> [--compare-baseline <file>] [--smoke] [--cleanup]`）

```text
1. 前置校验：
   - env 必填字段齐全（TESTING.md §6；缺 → refuse）
   - corpus content_hash 与 checkset 钉死值一致（不一致 → refuse）
   - 断言 er_checkpoint_enabled == False（读 settings；不满足 → refuse——
     防 P19 幂等重传导致空洞运行）
   - checkset schema 校验（--dry-run 模式只做本步，不上传不调 LLM）
2. 每 run（--runs N，默认 1）：
   a. 设置 ER_CHECKPOINT_ENABLED=0 → create_app（同 eval_p19_resume）
   b. TestClient 上传固定 corpus → novel_id / job_id
   c. 轮询 job 终态（completed / completed_with_errors / failed）
   d. Neo4j 稳定键快照（只读，自建 novel_id）
   e. 执行 checkset（含前置检查、失败 chunk 降级 G4）
   f. evidence dump（确定性原文检索）
   g. 落盘 result.json（runs/{run_id}/）
3. N>1：聚合 per-check pass-rate
4. --compare-baseline：与基线比较（§7）
5. report.py 生成 markdown（TESTING.md §9 模板 + 强制声明）
6. stdout 摘要（每 run 一行：novel_id / job 终态 / stable FAIL 数 / variance 观察数）
```

### 6.2 `--establish-baseline --runs N`（N≥3）

```text
1. 按 §6.1 跑 N 个 run（同一 compare_identity / checkset / corpus；N≥3）
2. 聚合 per_check → 按 §4.3 经验分类 stable/variance → **单独判定 satisfies_expected**
3. 计算 baseline_status（§7.3）：存在 stable failure → `INVALID_NOT_REGRESSION_SAFE`（事实照存 + stable_failures 列表），否则 `VALID`
4. 冻结基线 artifact → docs/evaluation/baselines/{baseline_id}.json
5. 生成基线摘要报告（markdown：per-check 表 + quality 汇总 + 观察记录 + **baseline_status 声明**）
6. 基线报告按 TESTING.md §9 存 docs/evaluation/（P20 阶段一交付物）
```

### 6.3 `--cleanup`（可选）

- dry-run：列出本次 run 创建的 novel_id（+ 计数）→ 人工确认 → `db.delete_novel(novel_id)` 精确删除（TESTING.md §7）；真实评估默认保留，清理需显式授权。

---

## 7. 判定与归因规则

### 7.1 回归判定表

| 情形 | 判定 | 动作 |
|---|---|---|
| stable 检查 FAIL（当前运行，基线 VALID） | **REGRESSION** | 告警；按该检查 attribution/layer 走归因路由（PIPELINE_LAYER §4） |
| variance 检查 FAIL（单次） | 观察（OBSERVATION） | 记录归因；不视为回归 |
| variance 检查 pass-rate 低于基线-容差 | drift 提示 | 记录 + 建议趋势复跑（不自动判回归） |
| INCONCLUSIVE / SKIP | 不计 | 记录原因 |
| compare_identity 不匹配（corpus_hash / checkset_version / model / chunk_size / chunk_overlap / chunker_version / extractor_version / prompt_hashes 任一不同） | **REFUSE_COMPARE** | 提示重建基线；**git_commit / git_dirty 差异不拒绝**（仅记录 provenance——回归比较的正常场景 = 不同 commit vs 历史基线） |
| 基线 baseline_status == INVALID_NOT_REGRESSION_SAFE | **REFUSE_COMPARE**（禁止正常 REGRESSION 判定） | 基线存在 stable failure，仅作诊断记录；修复后重建基线（§7.3） |

- **容差定义（基线时冻结）**：stable 检查 = 必须全部 PASS（出现 stable failure 使基线 INVALID，§7.3）；variance 检查 = pass-rate 相对基线下降超 ±1 run（N 较小时）或 ±20%（N≥5 时）→ drift 提示；具体容差在基线 artifact 中记录，可调但需显式修订。

### 7.2 归因路由

每个 FAIL 携带 checkset 中声明的 `attribution + layer`；报告输出「FAIL → 建议归因层 → 对应 Problem」映射（如 C1 FAIL → admission → P16-b/P018；A5 FAIL → merge → P08；D3 FAIL → registration → P017 D2），直接对接 Diagnostic Routing（PROBLEM.md §1）。

### 7.3 基线有效性（v1.1，阻断项 3）

> **不能把稳定失败冻结为「正常 baseline」。**

- **validity 条件（全部满足 → baseline_status = VALID）**：
  1. 基线 N≥3 次运行（决定性结果样本足够）；
  2. **无 stable failure**：全部 stable 检查 `satisfies_expected == true`（决定性结果全部 PASS）；
- **存在 stable failure（如 stable 检查 FAIL/FAIL/FAIL）**：
  - baseline artifact **照常保存事实**（outcome_distribution / stable_failures / stable 分类）；
  - `baseline_status = INVALID_NOT_REGRESSION_SAFE`；
  - **不允许用该基线对未来运行做正常 REGRESSION 判定**（compare → REFUSE_COMPARE，§7.1）；该基线仅作诊断记录——stable failure 本身即待处理的质量信号，按 attribution/layer 路由；
  - 修复后**重建基线**；
- **variance 检查**：不参与 validity——正常保存 outcome distribution 与 pass-rate（趋势参照）；
- 阶段一基线若出现 stable failure → 基线报告标注 INVALID + stable_failures 明细，转 observation / 新 Problem 立项（**不得静默视为「当前正常」**）。

---

## 8. evidence dump（人工复核材料）

- **确定性检索（零 LLM）**：用与 ingest 相同配置（chunk_size/overlap）对 corpus 重新 `read_epub + chunk_chapters`（确定性）→ 对每个 canonical 的每个 alias，在 chunk 文本中检索 mention 出现位置 → 输出 `{alias, chunk_id, chapter_id, snippet(±窗口)}`；
- **可选增强（ER_LINEAGE=1 时）**：并入 judge 事件（复用 D-8 observer 输出，只读，不改变判定）；
- **人工复核点**：P18 Do Not Reopen 纪律（顺顺 aliases 逐条可解释性核对）等语义检查——人工审 evidence dump 后回填 `annotations[]`（`{check_id, reviewer_note}`）；**annotation 不自动改判**，仅留档供报告引用；
- **产出物**：`runs/{run_id}/result.json#evidence_dump` + 报告「Alias Examples」节（自动填充）。

---

## 9. 与 P19 共存（约束 1 的落实）

| 项 | 做法 |
|---|---|
| checkpoint 语义 | **零改动**：store / 编排 / 指纹 / manifest 不动；harness 不 import checkpoint 模块 |
| fresh run | `ER_CHECKPOINT_ENABLED=0`（既有开关）→ 每次上传全新 novel_id（TESTING.md §3） |
| 守卫 | G5：run 后断言该 novel 无 `checkpoints/{novel_id}` 目录产生；配置断言 refuse（§6.1） |
| 复用 P19 资产 | 评估骨架（TestClient 上传/轮询/快照）从 eval_p19_resume.py 的经验提炼，不 copy checkpoint 逻辑 |
| 清理 | eval novel 默认保留；`--cleanup` dry-run + `delete_novel`（checkpoint 目录本就未产生） |

---

## 10. 代码改动清单

### 10.1 新增（全部在工具/测试/文档层；**backend/app 零改动**）

| 文件 | 内容 |
|---|---|
| `backend/tools/eval_framework/__init__.py` | 包导出 |
| `backend/tools/eval_framework/checks.py` | checkset v1 定义（§4.2 清单）+ 判定函数（纯函数：snapshot/stats → outcome；含前置检查、空洞防、降级 G4） |
| `backend/tools/eval_framework/runner.py` | 编排：env 采集 / 校验 refuse（TESTING.md §6 必填）/ compare_identity 计算与校验 / TestClient 上传 / 轮询 / 快照 / 检查 / result 落盘；`--smoke`（FakeLLMClient 注入，test_api_neo4j 模式） |
| `backend/tools/eval_framework/baseline.py` | 聚合 / §4.3 稳定性分类 / satisfies_expected / baseline_status 计算 / 冻结 artifact / compare（§7 判定表，含 REFUSE_COMPARE 与 INVALID 基线处理） |
| `backend/tools/eval_framework/evidence.py` | evidence dump（chunker 确定性检索 + 可选 lineage 事件） |
| `backend/tools/eval_framework/report.py` | TESTING.md §9 模板 markdown（强制声明） |
| `backend/tools/eval_framework/README.md` | 用法 / 纪律 / 与 TESTING.md 关系 |
| `backend/tests/unit/test_eval_checks.py` | checks 纯函数单测（合成快照 → 判定分类：PASS/FAIL/OBSERVATION/INCONCLUSIVE/SKIP、空洞防、归因路由、G5 守卫逻辑） |

### 10.2 修改（文档，实现阶段）

| 文件 | 内容 |
|---|---|
| `TESTING.md` §4/§5/§9 | 人工查询 → 指向 harness（「手工 Cypher 由 `run.py` 的 checkset 取代；报告模板仍权威；基线/比较用法见 eval_framework README」）；保留 §6 环境基线必填字段（harness 复用） |
| `PROBLEM.md` §2/§3/§5 | P20 条目（本轮已完成） |

### 10.3 明确不改

`backend/app/*`（含 `checkpoint/`）、`config.py`、`.env`、前端、`ARCHITECTURE.md`（eval_framework 是工具层，不入层表——如实现时认为需要一行指针可加，默认不加）。

---

## 11. 验收标准（P20 验收基准，必须逐条可验证）

> **AC-1（一键可重复）**：`python -u tools/eval_framework/run.py --runs 1` 产出 `result.json` + TESTING.md §9 模板 markdown（顶部含强制声明「本报告是 XX 版本的验证记录，不是下一轮修复方案…」）；result 含 TESTING.md §6 全部 env 字段。
>
> **AC-2（fresh run）**：每 run 全新 novel_id（checkpoint disabled 保证）；result 记录 novel_id；同 run 内无跨 novel 数据；两次连续运行 novel_id 不同。
>
> **AC-3（判定分类正确）**：合成数据单测 + 真实基线运行共同证明——D5 爸爸碎片 → OBSERVATION（非 FAIL）；merge 全 failed → INCONCLUSIVE；C1 父亲 非 Person → stable PASS（前置 顺顺 存在）；P16-b 冻结残留 → OBSERVATION；前置不满足 → SKIP（不计 PASS）。
>
> **AC-4（趋势）**：`--runs 3` 产出 per-check outcome_distribution + pass-rate；stable/variance 按 §4.3 经验分类（决定性结果全同 → stable，**含 stable failure**；混合 → variance），并单独判定 satisfies_expected。
>
> **AC-5（基线 + 比较）**：`--establish-baseline --runs 3` 冻结 `docs/evaluation/baselines/` artifact（含 baseline_status + compare_identity）；compare 时 stable FAIL → REGRESSION 告警、variance 波动记录归因、**compare_identity 不匹配 → REFUSE_COMPARE（git_commit 差异不拒绝）**、**INVALID 基线 → REFUSE_COMPARE（禁止正常 REGRESSION 判定）**。
>
> **AC-6（证据）**：evidence dump 产出 alias→原文上下文（chunk_id/chapter_id/snippet）；人工 annotation 可回填且不改判。
>
> **AC-7（语义零改动）**：`git diff` 无 `backend/app/*`、`config.py`、`.env` 改动；现有 unit（257）+ integration（16）全绿；P19 checkpoint 语义零接触（G5 守卫 + 配置断言）。
>
> **AC-8（清理纪律）**：`--cleanup` 先 dry-run 列出 novel_id，确认后按 id 精确删除；不删除未经确认的 novel。
>
> **AC-9（版本化）**：checkset schema_version + checkset_version + corpus content_hash 钉死；每条检查声明 attribution + layer；修改检查期望需 bump checkset 版本或独立立项（不得静默改判）。

---

## 12. 测试矩阵

### 12.1 unit（全 mock，无网络/Neo4j）

| 文件 | 用例 |
|---|---|
| `tests/unit/test_eval_checks.py`（新） | 每条检查的判定分类（合成 graph_snapshot/stats）：PASS / FAIL / OBSERVATION / INCONCLUSIVE / SKIP；**空洞 PASS 防**（前置不满足 → SKIP）；归因路由输出（FAIL → attribution + layer）；降级 G4（失败 chunk → 相关检查 SKIP/INCONCLUSIVE）；G5 守卫逻辑（checkpoint 目录存在 → run refuse 的判定函数部分） |

### 12.2 harness 自检（无真实 LLM）

- `run.py --dry-run`：checkset schema 校验 + env 字段校验 + corpus hash 校验 + 配置断言（不上传、不调 LLM）——每次改动 eval_framework 后必跑；
- `run.py --smoke`（可选）：`app.state.llm_client = FakeLLMClient()`（test_api_neo4j 模式）+ 真实 Neo4j——跑通上传→轮询→快照→检查骨架（mock LLM 输出固定 → 断言检查可执行、结果可落盘；不写真实基线）。

### 12.3 真实评估（基线运行，按 TESTING.md §3/§6/§9）

- `--establish-baseline --runs 3`（《边城》真实 LLM；`python -u` + 后台任务，PROCESS.md 运行纪律）；
- 每 run 记录 Environment Baseline；基线报告落 `docs/evaluation/`；
- 基线暴露的质量问题 → observation / 新 Problem 立项（**不在 P20 修复**）。

---

## 13. 阶段一交付物（先建立质量基线）

1. `backend/tools/eval_framework/`（checkset v1 + runner/baseline/report/evidence + README）；
2. `tests/unit/test_eval_checks.py` 全绿 + `--dry-run` / `--smoke` 通过；
3. **基线 artifact**：`docs/evaluation/baselines/biancheng-v0.2.9-<date>.json`（N=3 聚合 + §4.3 stable/variance 分类 + satisfies_expected + **baseline_status** + compare_identity）；
4. **基线报告**：`docs/evaluation/2026-08-28-biancheng-quality-baseline.md`（per-check 表 + quality 汇总 + observations；TESTING.md §9 模板 + 强制声明）；
5. TESTING.md §4/§5/§9 指向更新。

---

## 14. 边界与非目标

| 不做 | 原因 |
|---|---|
| 不把 harness 做成 pytest 集成测试 | TESTING.md §3：pytest 永远全 mock；真实 LLM 评估独立 |
| 不做 CI 门禁 / 自动触发 | 单次 ingest 15-25 分钟真实 LLM + token 成本；手动触发 + 基线比较 |
| 不进入性能优化 | 约束 3；judge 串行瓶颈已由 P19 profiling 记录（ESTIMATE），不在 P20 处理 |
| 不修 ER 质量问题 | 约束 4：基线暴露的问题另立立项 |
| 不重开 P16/P17/P18 / 不改检查期望 | 约束 2：期望修改 = 决策修改 |
| 不修改 P19 checkpoint 语义 / 不让 eval 复用 checkpoint | 约束 1 + fresh-novel 纪律（§9） |
| 不自动判定 aliases 语义可解释性 | P18 教训：语境理解不可自动化；evidence dump + 人工复核 |
| 不建通用多语料框架 | 语料锁《边城》（D-7/D-16 项目级规则哲学）；换语料需重建 checkset + 基线（独立立项） |
| 不生成逐 run 的「结论性」判定 | 单次运行不结论（P06）：只产事实 + 分类；结论需趋势/基线 |

---

## 15. 实施顺序（Review 通过后执行；本 Spec 不实现）

```text
Step 1  checks.py（checkset v1 + 判定纯函数）+ test_eval_checks.py 单测
Step 2  runner.py（env 采集/refuse/dry-run/smoke）+ evidence.py
Step 3  baseline.py（聚合/分类/冻结/compare）+ report.py
Step 4  README + TESTING.md §4/§5/§9 指向更新
Step 5  --dry-run + --smoke 自检；全量回归（unit 257 + integration 16）
Step 6  基线运行（--establish-baseline --runs 3，真实 LLM，后台任务）
Step 7  基线报告（docs/evaluation/）→ 回写 P020；基线暴露问题记录 observation/新立项
Step 8  commit（一个问题一个 commit，PROCESS.md §3）
```

---

## 16. Review Round 1 检查清单（实现前必须逐项确认）

- [ ] **约束落实**：P19 checkpoint 语义零改动（§9 + G5 守卫）；P16/P17/P18 冻结语义编码（§4.2 C/D 组 OBSERVATION 语义）；无性能优化内容（§14）；阶段一 = 基线本体（§13）；**v1.1 三项修订（§4.3 稳定性分类 / compare_identity / §7.3 基线有效性）已合入**；
- [ ] **判定分类**：OBSERVATION / INCONCLUSIVE / SKIP 语义与 AGENTS.md §3 红线一致（爸爸 碎片、翠翠的祖父、merge INCONCLUSIVE 不判 FAIL）；
- [ ] **空洞 PASS 防**：每条 stable 检查的前置条件完备（C1 前置 顺顺 存在等）；
- [ ] **fresh-run 保证**：`er_checkpoint_enabled=False` 配置断言 + G5 目录守卫（防 P19 幂等空洞运行）；
- [ ] **env 强制与 compare 身份（v1.1）**：TESTING.md §6 字段缺失 → refuse（provenance 必填）；compare 兼容性由 **compare_identity** 判定（§5.2/§7.1）——**git_commit 差异不拒绝比较**；不兼容才 REFUSE_COMPARE；
- [ ] **stable/variance 定义（v1.1）**：决定性结果全同 → stable（**含 stable failure**）；混合 → variance；stable/variance 只描述稳定性，satisfies_expected 单独判定（§4.3/§5.2）；
- [ ] **基线有效性（v1.1）**：stable failure → baseline_status = INVALID_NOT_REGRESSION_SAFE（事实照存但禁止正常 REGRESSION 判定）；variance 检查正常保存分布（§7.3）；
- [ ] **版本化**：checkset_version / schema_version / corpus_hash 钉死；期望修改流程（bump 或独立立项）明确；
- [ ] **归因路由**：FAIL → attribution + layer → PROBLEM.md §1 Diagnostic Routing 映射正确（§7.2）；
- [ ] **数据安全**：harness 只读 Neo4j + 自建 novel_id；`--cleanup` dry-run 先行；真实评估默认保留（TESTING.md §7）；
- [ ] **可测性**：checks 纯函数可单测（合成数据）；dry-run / smoke 覆盖骨架；
- [ ] **Do Not Reopen 检查**（P020 §20）：无同类记录冲突；无旧方案被证伪；不重复旧修复；不把 P20 当 ER 修复通道。

---

## 附录：与现有文档的关系

| 文档 | 关系 |
|---|---|
| [P020 Problem Record](../problems/P020-evaluation-framework.md) | 本 Spec 的 Evidence / 边界 / Decision 依据 |
| `TESTING.md` §4/§5/§9 | checkset 的期望来源；实现阶段更新为「人工查询 → harness」指向 |
| `PROCESS.md` §2/§5 | 真实评估纪律（fresh novel / 变量固定 / 验收顺序）；本 Spec 满足准入 |
| `PIPELINE_LAYER.md` §4 | checkset 每条检查的 layer 归因来源 |
| `DECISIONS.md` D-5/D-6/D-9/D-10/D-13/D-17 | 冻结语义的编码边界（OBSERVATION 不判败） |
| `DECISIONS.md` D-18（P19） | 约束 1：eval 以 `er_checkpoint_enabled=False` 共存，checkpoint 语义零改动 |
| `ARCHITECTURE.md` | 不修改（eval_framework 为工具层，不入层表） |
| `docs/evaluation/` | 基线报告与历次人工评估报告同目录（阶段一交付物） |
