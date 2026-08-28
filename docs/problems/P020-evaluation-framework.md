# P020 — 人工 Neo4j 验收不可重复执行，缺质量基线（Evaluation Framework）

- **Status**: ✅ implemented + 首份真实基线已产出（2026-08-28，3 run，deepseek-v4-flash-0731）——**baseline_status=INVALID_NOT_REGRESSION_SAFE（A1 稳定失败 FAIL×3）**：框架按 v1.1 有效性机制如实暴露质量问题并禁止用于回归比较；A1（老二 未并入 傩送，P08 域）修复另立跟进
- **Severity**: High（质量回归风险：验收人工化、不可重复、无冻结基线，代码改动后无法系统性比对真实行为漂移）
- **Domain**: 测试与评估 / 流程
- **Tags**: evaluation, regression, quality-baseline, neo4j-acceptance, repeatability, llm-nondeterminism, checkset
- **First Seen**: V0.2.x 历次真实评估（每次人工 Cypher 查询 + 人工对照 TESTING.md §4/§9.1 期望 + 手写报告）
- **Last Verified**: 2026-08-28（审计历次评估报告 + TESTING.md §4/§5/§9.1：验收步骤全部为人工；检查定义散落在散文/报告中，无可执行形态）
- **Evidence Level**: HIGH（历次评估报告可复现；人工流程为文档/报告事实）
- **Decision Type**: FACT（现状：验收人工化）+ DESIGN_DECISION（P20 方向已定：可重复 regression evaluation + 质量基线，见 Spec）
- **Related Problems**: P06（judge/extraction 非确定性 → 趋势与方差设计）/ P08、P09（基线检查来源）/ P11（merge 全 failed → INCONCLUSIVE）/ P16、P17、P18（检查集来源与冻结语义编码，D-5/D-6/D-9/D-10/D-13/D-17）/ P19（共存：eval 强制 checkpoint disabled；复用其 TestClient 评估流程）/ P04、P05（LLM 失败 → run 失败记录与降级）
- **Related Commits**: 无（新立项）
- **Related Evaluation Reports**: 历次人工评估报告即本问题的证据源（`docs/evaluation/2026-08-2{1,6,7,8}-*.md`）

## 1. Context

每次真实评估（V0.2.5 / V0.2.6 / Task A / P19）都走同一条人工验收链：

1. 上传固定语料《边城》EPUB → 等待 job 终态（真实 LLM）；
2. 记录 Environment Baseline（TESTING.md §6）；
3. 用 Cypher 直接查询 Neo4j（TESTING.md §5 的三段查询）；
4. 人工对照 TESTING.md §4 基线期望（傩送/二老、天保/大老、老船夫/爷爷/老人、负向）与 §9.1 版本化指标（非正文 canonical、provisional、DESCRIPTIVE、ch5b、P18 sink）；
5. 人工翻原文做 aliases 可解释性核对（P18 Do Not Reopen 纪律）；
6. 手写 markdown 报告（TESTING.md §9 模板 + 强制声明）。

这条链的问题：

- **检查定义不可执行**：期望写在散文与历史报告里，每次评估由人重新解释，查询口径逐份报告漂移（如 aliases 排序、chapters 集合、负向判定标准不完全一致）；
- **单次运行不结论**：P06 非确定性要求多次取趋势，但人工多运行成本高（每次 15-25 分钟真实 LLM），实际从未系统做过趋势；
- **无质量基线**：没有冻结的「当前质量水平」数字，无法回答「某次代码改动后质量是否回退」；
- **回归不可比**：unit 测试全 mock（TESTING.md §3），真实行为只被一次性人工评估覆盖；改动 resolver 后无重复性真实回归门禁。

## 2. Symptom

- 每份评估报告需要 30-90 分钟人工执行与撰写，且执行质量依赖操作者；
- 「上一版 PASS / 这一版 FAIL」无法与代码改动建立可靠因果（单次运行 + 方差）；
- 无法回答「当前系统质量基线是多少」（如 傩送/二老 归并成功率、父亲 拦截成功率）；
- 冻结决策的残留（D5 爸爸碎片、P06 翠翠的祖父、merge INCONCLUSIVE）在每次报告中重复人工解释，且存在被误判为 FAIL 的风险（AGENTS.md §3 已多次强调）。

## 3. Impact

- 质量回退可能在代码改动后未被发现（无重复性真实回归检测）；
- 每次评估的结论可信度受限（单次运行、人工口径漂移），归因链条（PIPELINE_LAYER §4）依赖的观测数据不稳定；
- 人工成本挤占「建立基线 → 改进 → 再验证」的循环，拖慢后续问题（P06/P08/P09/P17 等）的闭环；
- 冻结语义（D-6 P16-b frozen、D-9、D-10）在人工解读中反复出现误判风险，浪费归因轮次。

## 4. Trigger

- 任何需要「真实行为验证」的改动（resolver / prompt / hygiene / merger / schema / judge 相关）之后的验收环节；
- 需要回答「质量是否回退 / 基线是多少」的决策时刻；
- 新问题归因需要多次运行取趋势（P06 纪律）时。

## 5. Timeline

- **T1（V0.2.1-V0.2.4）**：历次真实评估人工执行；TESTING.md §4 基线期望成型。
- **T2（V0.2.5-V0.2.6）**：§9.1 版本化验收指标出现；每次报告重复人工核对（非正文/描述性/P16-b 词表），口径开始漂移。
- **T3（V0.2.7 Task A）**：lineage 观测上线（D-8）——归因手段自动化，但**验收本身**仍人工。
- **T4（V0.2.8 P19）**：P19 评估脚本（`tools/eval_p19_resume.py`）证明「TestClient + 真实 LLM + Neo4j 快照」可脚本化；评估耗时记录（judge 串行 ≈ 65-80%）。
- **T5（2026-08-28）**：立项 P20。审计确认验收全链人工；方向 = 可重复 regression evaluation + 质量基线；产出本 Record + Spec，待 Review。

## 6. Initial Hypothesis

「人工验收需要换成自动化测试」→ 设计阶段被修正为分层结论：

- **可脚本化的部分**（Neo4j 断言、统计、报告、趋势聚合）→ 自动化（checkset + runner）；
- **不可脚本化的部分**（aliases 语义可解释性核对，P18 Do Not Reopen 纪律）→ 收敛为 **evidence dump 复核**（自动产出 alias→原文上下文证据，人工只审证据文件，不再翻书）；
- **不能做成 pytest**：真实 LLM 评估与 pytest 分离（TESTING.md §3），pytest 永远全 mock；
- **不能做 CI 门禁**：token 成本高（每次全量 ingest），保持手动触发。

## 7. Investigation Path

```text
Step 1  审计 TESTING.md §4/§5/§9.1：验收期望与查询的权威位置（散文形态）
Step 2  审计历次评估报告（2026-08-21/26/27/28）：实际执行的检查清单与口径漂移点
Step 3  审计 tools/eval_p19_resume.py：TestClient + 真实 LLM + Neo4j 快照的可复用骨架
Step 4  审计 config.py：er_checkpoint_enabled 开关（eval 强制 disabled 的可行性）
Step 5  审计 checkpoint 层：确认 eval 不 import checkpoint / 不写 checkpoints 目录即可零语义接触
Step 6  审计 PIPELINE_LAYER §4 归因链：检查集的 layer/attribution 字段来源
Step 7  审计 D-5/D-6/D-9/D-10/D-13/D-17 与 P16/P17/P18：冻结语义的编码边界（哪些结果必须判 OBSERVATION 而非 FAIL）
```

## 8. Experiments

（设计阶段，尚未实施。计划中的验证实验见 §15 Validation 与 Spec §12/§13；核心为基线运行（N≥3 真实 LLM）+ checks 纯函数单测（合成快照断言判定分类）。）

## 9. Evidence

- **doc evidence（TESTING.md §4/§5/§9.1）**：验收期望为散文；§5 是唯一「半自动」部分（三段 Cypher）；§9.1 指标随版本演进但无执行形态。
- **report evidence（历次评估）**：每份报告人工重建查询与判定（如 V0.2.6 的 `顺顺 aliases=[船总顺顺, 中年人, 爹爹]` 需人工 Cypher + 人工解释）；merge 均以 `failed_pairs=all → INCONCLUSIVE` 人工标注。
- **code evidence（eval_p19_resume.py）**：上传/轮询/快照/计数已可脚本化（P19 评估复用同一骨架两次运行）。
- **code evidence（config.py）**：`er_checkpoint_enabled`（默认 True）——eval 设 False 即回退 pre-P19 行为、每上传全新 novel_id，满足 TESTING.md §3 fresh-novel 纪律且零改动 checkpoint 语义。
- **code evidence（test_api_neo4j.py:145）**：`app.state.llm_client = FakeLLMClient()` 注入模式可行 → harness 可选 `--smoke`（mock LLM + 真实 Neo4j）自检骨架。

## 10. Root Cause

验收标准（期望）与验收执行（查询/判定/报告）**耦合在人工环节**：期望只有散文形态，执行只有人工形态，二者都没有可重复执行、可版本化、可聚合的载体 → 无法建立基线、无法做回归比较、无法做趋势。

## 11. Ruled-out Causes

- ~~做成 pytest 集成测试~~：TESTING.md §3 硬性分离——pytest 永远全 mock；真实 LLM 评估走独立脚本/手动流程。
- ~~做成 CI 门禁~~：单次全量 ingest 15-25 分钟真实 LLM、token 成本高，不适合每次 push 触发；保持手动触发 + 基线比较。
- ~~用 P19 checkpoint 做「复用」加速评估~~：违反「不修改 P19 checkpoint 语义」约束；且复用会使每次评估失去 fresh-novel 语义（P19 幂等重传 → 同一 novel_id → 空洞运行）。**正确做法 = eval 强制 `er_checkpoint_enabled=False`**。
- ~~自动判定 aliases 语义可解释性~~：需要读小说原文理解语境（顺顺 vs 翠翠之父 的 父亲 指代），LLM/规则都会误判；保留人工复核（P18 纪律），只自动化证据产出。
- ~~用 lineage 事件直接生成检查结论~~：lineage 是旁路 observer（D-8），事件含 judge 输入输出但非「验收期望」的判定者；只用作证据补充。

## 12. Failed Approaches

- 无（新立项；设计阶段的排除项见 §11）。

## 13. Correct Approach

构建独立评估工具包 `backend/tools/eval_framework/`：

- **checkset（声明式检查集 v1）**：把 TESTING.md §4/§9.1 + P16/P17/P18 验收编码为可执行检查；每条检查带 `id / group / expectation / outcome_class / attribution(D-XX|PXX) / layer(归因链)`；**修改检查期望 = 修改决策**（需独立立项/解除冻结）；
- **判定分类**：`PASS / FAIL / OBSERVATION / INCONCLUSIVE / SKIP`——已知限制与冻结残留（D5 爸爸碎片、P06 方差、merge INCONCLUSIVE）判 **OBSERVATION 不判 FAIL**，编码冻结语义，杜绝人工误判；
- **run**：`run.py --runs N`——强制 `er_checkpoint_enabled=False`（既有开关），TestClient 上传固定语料（《边城》，content_hash 钉死）→ 轮询终态 → Neo4j 稳定键快照 → 执行 checkset → 产出 `result.json`；
- **baseline**：首次 N≥3 运行聚合 per-check pass-rate → 经验分类 stable/variance → 冻结基线 artifact（`docs/evaluation/baselines/`）；**阶段一交付物 = 基线本体，不修任何 ER 质量问题**；
- **compare**：未来单次运行与基线比较——stable 检查 FAIL = **REGRESSION** 告警；variance 检查波动记录归因；环境基线不匹配拒绝比较；
- **evidence dump**：对每个 canonical 的 alias 做确定性原文上下文检索（chunker 重切 + 文本窗口，零 LLM），人工复核材料自动化；复核结论可回填 `annotation`（不自动判）；
- **report**：自动生成 TESTING.md §9 模板 markdown（含强制声明「本报告是 XX 版本的验证记录，不是下一轮修复方案…」）。

详见 `docs/superpowers/specs/2026-08-28-p020-evaluation-framework-design.md`。

## 14. Invariants

- **P19 checkpoint 语义零改动**（约束 1）：checkpoint store / 编排 / 指纹不动；eval 以 `er_checkpoint_enabled=False` 运行；harness 不 import checkpoint 模块、不写 checkpoints 目录；并有守卫检查（G5：run 后断言该 novel 无 checkpoint 目录产生）；
- **P16/P17/P18 决策不重开**（约束 2）：D-5/D-6/D-9/D-10/D-13/D-17 冻结语义编码进 checkset 的 attribution/outcome_class；已知限制必须 OBSERVATION；不得以「FAIL」形式重开冻结问题；
- **不进入性能优化**（约束 3）：无计时门禁、无 profiling 交付物；耗时仅作为观察记录（P19 已做过 profiling，不重复）；
- **先建立质量基线**（约束 4）：P20 阶段一 = 基线本体；基线暴露的质量问题只记录为 observation/follow-up，不在 P20 修复；
- fresh-novel 纪律：每 run 全新 novel_id（TESTING.md §3）；真实评估结果默认保留（§7）；
- 数据安全：harness 只读 Neo4j + 自建 novel_id；清理走 dry-run + `db.delete_novel` 精确删除；
- 报告强制声明：自动报告顶部必须含 TESTING.md §9 声明语句；
- pytest 分离：checks 纯函数单测可入 pytest（全 mock）；真实评估永远不混入 pytest。

## 15. Validation

核心验收标准（P20 验收基准，用户指定）：

> **人工 Neo4j 验收固化为可重复执行的 regression evaluation：一条命令（`run.py --runs N`）产出结构化 result + 自动报告；N 运行产出 per-check pass-rate；首次运行冻结质量基线；后续运行可与基线比较并区分 REGRESSION / 观察波动。**

- **AC-1 一键可重复**：`run.py --runs 1` 产出 `result.json` + TESTING.md §9 模板 markdown（含强制声明）；Environment Baseline（TESTING.md §6）全字段在 result 中；
- **AC-2 fresh run**：每 run 全新 novel_id（checkpoint disabled 保证）；result 记录 novel_id；无跨 run 数据复用；
- **AC-3 判定分类正确**：D5 爸爸碎片 → OBSERVATION（非 FAIL）；merge 全 failed → INCONCLUSIVE；父亲 非 Person → stable 期望；P16-b 冻结残留 → OBSERVATION；空洞 PASS 被前置条件防住；
- **AC-4 趋势**：`--runs N` 聚合 per-check outcome_distribution + pass-rate；stable/variance 按**决定性结果稳定性**分类（全同 → stable 含 stable failure；混合 → variance），satisfies_expected 单独判定；
- **AC-5 基线 + 比较**：基线 artifact 冻结（含 baseline_status + compare_identity）；compare 时 stable FAIL → REGRESSION 告警、variance 波动记录归因、**compare_identity 不匹配 → REFUSE_COMPARE（git_commit 差异不拒绝）**、**INVALID 基线禁止正常 REGRESSION 判定**；
- **AC-6 证据**：evidence dump 产出（alias→原文上下文 + chunk/chapter id）；人工复核结论可回填 annotation；
- **AC-7 语义零改动**：`backend/app/*`（含 checkpoint/）零改动；现有 unit（257）+ integration（16）全绿；config 仅读既有开关；
- **AC-8 清理纪律**：`--cleanup` dry-run 列 novel_id → 确认 → 精确删除（TESTING.md §7）；
- **AC-9 版本化**：checkset schema_version + checkset_version + corpus content_hash 钉死；检查声明 attribution/layer；修改期望需 bump 版本或独立立项。

## 16. Trade-offs

- **真实 LLM 成本**：基线 N≥3 次全量 ingest（每次 15-25 分钟、百万级输入 token）——这是「建立质量基线」的必要代价（用户指定先建基线）；单次 compare 运行 1 次即可，成本可控；
- **方差容忍**：variance 检查不做硬 PASS/FAIL（P06 纪律），代价是部分质量信号只有趋势意义、不能单次断言——与「不把单次真实评估当 deterministic fact」（Rule 8）一致；
- **语料锁定**：基线先锁《边城》（content_hash 钉死）——检查期望（词表、家族关系）是项目级规则（D-7/D-16 同哲学），换语料需重新评估与基线，不追求通用框架；
- **人工保留**：aliases 语义可解释性核对保留人工（证据自动产出、结论人工判定）——避免用 LLM/规则假装理解语境（P18 教训）；
- **不做 CI 门禁**：手动触发 + 基线比较——避免高频 token 消耗，同时保留回归检测能力。

## 17. Decision（已确认设计选择，2026-08-28）

| # | 决策 | 内容 |
|---|---|---|
| 1 | 形态 | 独立工具包 `backend/tools/eval_framework/`；非 pytest、非 CI 门禁；手动触发 |
| 2 | fresh run | 强制 `er_checkpoint_enabled=False`（既有开关）→ 每 run 全新 novel_id；**P19 checkpoint 语义零改动** |
| 3 | 检查集 | 声明式 checkset v1（TESTING.md §4/§9.1 + P16/P17/P18 验收编码）；每条检查带 attribution + layer |
| 4 | 判定分类 | PASS / FAIL / OBSERVATION / INCONCLUSIVE / SKIP；已知限制与冻结残留 = OBSERVATION 不判败 |
| 5 | 稳定性分类 | stable/variance 按**决定性结果稳定性**分类（全部 PASS → stable；全部 FAIL → stable failure；混合 → variance）；**stable/variance 描述稳定性不描述 correctness**；satisfies_expected 单独判定；stable FAIL（当前运行）= REGRESSION；variance 波动记录归因 |
| 6 | 基线 | 首次 N≥3 运行冻结基线（docs/evaluation/baselines/）；**存在 stable failure → baseline_status = INVALID_NOT_REGRESSION_SAFE（事实照存，禁止用于正常 REGRESSION 判定）**；阶段一 = 基线本体，不修质量问题 |
| 7 | 证据 | evidence dump（确定性原文检索）供人工复核（P18 纪律）；annotation 回填不自动判 |
| 8 | 报告 | 自动 markdown（TESTING.md §9 模板 + 强制声明）；环境基线缺失 → refuse；git_commit 仅作 provenance，compare 兼容性由 compare_identity（语义身份）判定 |
| 9 | 边界 | 不进入性能优化；语料锁《边城》；扩展语料/CI 化需独立立项 |
| 10 | 流程 | Problem Record + Spec → Review → 实现 → 基线运行（真实 LLM）→ 基线报告 → commit |

### Review Round 1 修订（2026-08-28，三项阻断修订，合入 Spec v1.1）

| # | 阻断项 | 修订 |
|---|---|---|
| 1 | stable/variance 定义错误（pass-rate=1.0 → stable 会把稳定失败误判为 variance） | 按**决定性结果稳定性**分类：全部 PASS → stable；全部 FAIL → **stable（stable failure）**；混合 → variance；**稳定性 ≠ correctness**；satisfies_expected 在分类后单独判定 |
| 2 | compare 以 git_commit 作拒绝条件，阻断回归比较的正常场景（不同 commit vs 历史基线） | git_commit / git_dirty 仅作 **provenance**；compare 兼容性由 **compare_identity**（corpus_hash + checkset_version + model + chunk_size + chunk_overlap + 语义版本：chunker/extractor/prompt hashes）判定，不兼容才 REFUSE_COMPARE |
| 3 | 稳定失败可被冻结为「正常 baseline」 | 新增 **baseline validity**：stable failure → baseline_status = `INVALID_NOT_REGRESSION_SAFE`（事实照存 + stable_failures），**禁止正常 REGRESSION 判定**；variance 检查正常保存 outcome distribution |

## 18. Follow-up

1. Spec Review Round 1（2026-08-28 初稿，待评审）；
2. 实现（Spec §10 文件清单：eval_framework 包 + checks 单测 + TESTING.md §4/§5/§9 指向更新）；
3. unit（checks 纯函数）+ dry-run 自检；
4. **基线运行（N≥3，真实 LLM，《边城》）→ 冻结基线 artifact + 基线报告**（阶段一交付物）；
5. 基线报告回写本 Record；基线暴露的质量问题分别记录为 observation / 新 Problem 立项（**不在 P20 修复**）。

**执行结果（2026-08-28）**：

- ✅ **实现完成**：Step 1-5（checkset v1 / runner / evidence / baseline / report + README + TESTING.md 指向 + G1/G3 修订 + 自检），commits `070711c`（docs）→ `8adf37a`（Step 1）→ `8c684ee`（Step 2）→ `71ea076`（Step 3）→ `c738367`（Step 4）→ `c3b99d7`（Step 5 路径修复）→ `703f434`（Step 5.1 G1/G3）→ `2e7e47b`（超时 2h）；全量 343 unit + integration 零回归；
- ✅ **首份真实基线（Step 6，deepseek-v4-flash-0731，并发 4，fresh novel ×3，checkpoint 禁用）**：
  - 3 run 全部 `completed`（0 failed chunk），novel `070c03ce…` / `40d057fb…` / `681538d9…`（另 1-run 验证 novel `f4c78364…`，均按 TESTING §7 保留）；
  - **baseline_status = `INVALID_NOT_REGRESSION_SAFE`**（v1.1 有效性机制如实工作）：**A1 稳定失败（FAIL×3）**——deepseek 下 `老二` 未并入 `傩送` aliases（P08/extraction/recall 域，**新 Problem 立项候选**，不在 P20 修复）；
  - **C2（翠翠的父亲 拦截）3/3 PASS → stable**——P16-b qualified admission **未系统性失守**（1-run 的单次 FAIL 判为方差，非规则缺口）；
  - C1 父亲 拦截、C4 sink 收敛（本轮 3/3 PASS）、C3 爹爹 confirmed（2/3 FAIL，variance）、A2 天保/大老（2/3，variance）；A3/A4/A6/D1 等 1-run 的 FAIL 在 3-run 均收敛为 stable PASS（单次波动）；
  - **F1 merge**：2/3 INCONCLUSIVE（merge_judge 400——**6MB 请求体超限 / input length**，P19 已知既有行为）+ 1/3 OBSERVATION（0 pairs）——merge 层质量在 P20 域内不可判（记录，独立跟进）；
  - 基线 artifact：`docs/evaluation/baselines/biancheng-2026-08-28-deepseek-v4-flash-0731.json`；基线报告：`docs/evaluation/2026-08-28-biancheng-quality-baseline.md`；
  - **未修改任何 expectation / resolver / pipeline 适配本轮结果**；Neo4j 无污染（labels 仅 Novel/Person）、checkpoint 目录零新增（G5 物理验证）。

## 19. Current Limitation

实现后已知限制（含首份基线暴露项）：

- 基线是**记录**不是门禁：只提供回归比较，不自动阻断（手动触发）；
- 语义可解释性核对仍人工（证据自动、判定人工）；
- 语料锁《边城》；新语料需重建检查集与基线（项目级规则哲学，D-7/D-16）；
- 单次 compare 运行成本 ≈ 一次全量 ingest（token + 时间）；
- 环境漂移（换模型 / 换 chunk 配置）使旧基线不可比较（需新基线）；
- variance 检查单次 FAIL 不构成回归证据（需趋势）；
- **首份基线为 INVALID_NOT_REGRESSION_SAFE**（A1 稳定失败）——在 A1 修复并重建基线前，不得用其做正常回归比较；
- **merge 层不可判**：merge_judge 请求体超 DashScope 6MB / input length 上限（P19 已知既有行为）→ F1 恒 INCONCLUSIVE/观察，merge 质量在 P20 域内无信号（独立跟进）。

## 20. Do Not Reopen

- 若「人工验收又出现」再现，先检查（按序）：
  1. **harness 是否被绕过**（人工又去跑 Cypher 而非 `run.py`）；
  2. **checkset 是否过时**（新版本行为变化未 bump checkset 版本）；
  3. **基线是否失效**（环境变化 / 语料变化 → 旧基线不可比较，需重建）；
  4. **code regression**（eval_framework 自身被改动 / checks 判定逻辑被削弱）。
- 不要重复「验收只能人工」的旧假设；不要把 checkset 期望当「修复指令」（期望修改 = 决策修改，需独立立项）。
- 不要在 P20 内修复 ER 质量问题（基线暴露的问题另立 Problem Record，PROCESS.md §7：Real evaluation 先于结论）。
- 不要为了让 eval 变快而修改 P19 checkpoint 语义或让评估复用 checkpoint（fresh-novel 纪律 + 约束 1）。
