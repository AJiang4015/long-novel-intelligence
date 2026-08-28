# 项目最终化路线图（Finalization Roadmap）

> 定位：从「持续开发」切换到「有限收口 + 面试化准备」的规划文档。
> 依据当前仓库状态（2026-08-28）整理，只回答 7 个收口问题；**不包含**新功能、新 Problem、checkset 修改或评估计划。
> 权威记录：`DECISIONS.md`（D-1..D-19）、`PROBLEM.md`（P01-P21）、`ARCHITECTURE.md`、各 `*_LAYER.md`、`TESTING.md`。

**当前状态锁定（上下文）**：

```text
P020 = CLOSED            （Evaluation Framework 已交付，baseline/compare CLI 未接）
P021 = CLOSED / accepted （D-19：单次低显著性 mention 不要求稳定覆盖）
P017 = ACTIVE / D5-a 新增「爹爹」实例（C3）
C3   = hard gate / stable failure（未降级）
v2 baseline = INVALID_NOT_REGRESSION_SAFE（stable_failures=[C3]，已提交保留）
```

---

## 1. 当前已经完成并可以冻结的能力

| 能力 | 状态 | 冻结依据 |
|---|---|---|
| 端到端 ingest pipeline（EPUB→sections→chunker→extractor→hygiene→resolver→merger→Neo4j） | ✅ 全链路真实评估覆盖 | ARCHITECTURE / PIPELINE_LAYER / 历次 eval 报告 |
| P16-a 非正文污染治理（provisional/promotion/flush） | ✅ 已解决并验证 | P016 / V0.2.5-a eval |
| P16-b 正文角色称谓 admission gate（D-5/D-6） | ✅ 机制验证通过，**冻结** | D-5 / D-6 / V0.2.6 eval |
| P17 B1 deferred + D-5-b（generic+judge-null 不注册） | ✅ 已实现并验证 | D-9 / D-17 / V0.2.8 |
| P06 lineage 可观测性（D-8，默认关零开销） | ✅ 归因基础设施 | D-8 / D-11 / Task A eval |
| P19 checkpoint / resume（D-18） | ✅ 实现 + 真实评估（零重复调用） | D-18 / P19 eval |
| **P20 Evaluation Framework**（checkset v2 24 条 + runner/evidence/baseline/report） | ✅ 已交付；基线 v1/v2 已产出（INVALID 如实保留） | P020 / checkset v2 / D-19 |
| 测试体系（345 unit+integration 全绿）+ 真实评估纪律 | ✅ | TESTING.md |
| 数据安全治理（novel_id 隔离 / delete_novel / D-3 边界） | ✅ | AGENTS §2 / D-2 / D-3 |

**结论**：以上均可作为演示/面试的功能与工程基线，无需再开发。

## 2. 当前剩余的真正阻断项

| # | 阻断项 | 性质 | 影响 |
|---|---|---|---|
| 1 | **merge_judge 请求体超限（DashScope 6MB / input length）** | 功能级缺陷（既有行为，P19 已记录） | 《边城》桥接证据过大时 merge 恒 400 → **merge 层完全不可判**（F1 恒 INCONCLUSIVE）、合并关系质量无信号、demo 完整性受损 |
| 2 | **P20 基线 INVALID（C3 stable failure）** | 诚实状态（非缺陷） | 回归比较门禁不可用；根因在 extraction coverage（P017 D5-a 域，见 Q4），**不是**框架问题 |
| 3 | **LLM 运行成本/速度**（judge 串行为主，P19 测占 65-80% 耗时） | 性能项（用户约束：不做性能专项） | 3-run 验证与 demo 时间成本高（单 run ~13 分钟/并发 4） |
| 4 | 部署/启动工程化缺失（无一键启动、无 CI 骨架、无顶层项目 README） | 工程化项 | 面试/交付体验（见 Q6） |

**非阻断（明确不算）**：C3 稳定失败（已归因，P017 D5-a，产品决策待定）；C2/C4/A2/C3 的 variance 波动（趋势项，未达立项）；v2 基线 INVALID（框架如实工作的证据）。

## 3. 性能专项建议优先级

> 约束：用户明确「不进入性能优化」。下列仅用于**收口决策参考**，非开发计划。

| 优先级 | 项 | 性质 | 建议 |
|---|---|---|---|
| **P0** | merge_judge 6MB 请求体 | **功能阻断，不是纯性能** | 唯一值得在本阶段处理的"性能相关"项——方向：桥接证据截断/采样（复用 EVIDENCE_CAP）、分批 judge、或明确降级语义；**若不做，至少作为已知限制写进面试清单** |
| P1 | judge 串行耗时 | 性能 | **不建议做**：resolver 跨 chunk 有状态（known 持续累积，PIPELINE_LAYER §7 chunk_id 升序确定性），跨 chunk 并发会破坏确定性；单批内已并发。可行但低优先：judge 输入正文压缩 |
| P2 | extract 并发调优 | 性能 | 已是并发；仅调 concurrency（运营参数），不做代码改动 |
| P3 | 模型选择/成本（flash vs max） | 运营决策 | 非代码；由基线模型绑定（compare_identity 含 model） |

**结论**：性能专项整体**不进入收口范围**；唯一例外是 P0（merge 可用性，属功能修复）。

## 4. P017 D5-a「角色称谓 extraction coverage」后续决策点

**当前立场（维持）**：接受 + 记录——C3 保留 hard gate、v2 基线 INVALID 如实；不实施 prompt B / 换模型探针 / 结构规则（本轮与用户确认）。

**决策触发器（何时才需要重新决策）**：

1. **产品需求证据出现**：真实需求/面试场景明确要求「角色称谓（爸爸/爹爹/母亲）必须出现在知识图谱」——目前无此证据；
2. **生产模型变更**：换模型后重建基线时天然复评（例如新模型对角色称谓覆盖改善，C3 可能转 PASS→基线 VALID→A7 类观察可评估升级）；
3. **负面反馈**：用户在 demo 中看到「爹爹 不在图」并视为缺陷。

**决策时的候选路线（届时再评，现在不做）**：

| 路线 | 依据 | 推荐度 |
|---|---|---|
| 接受为 Known Limitation（当前立场） | cd52844（prompt B 边际收益低 + descriptive 污染风险）；爹爹 5 次出现但系统价值低 | 维持（默认） |
| 换模型复评 | qwen3.7-max 曾正确提取 爹爹（V0.2.6 实证）——模型差异存在 | 需求出现时最先试（1-run 探针，成本低） |
| prompt 增强 | cd52844 已证收益有限 | 不推荐 |
| 结构规则（称谓近形召回） | D-10 允许，但复杂度/污染风险高 | 最后选项 |

**建议话术（面试）**：定位为「已知模型能力边界 + 全程可观测（lineage 归因 + A7/C3 趋势）」——展示的是归因与治理能力，而非隐藏缺口。

## 5. `--establish-baseline / --compare-baseline` 何时接最合理

- **现状**：纯函数接口（`baseline.aggregate_runs` / `baseline.compare_run` / `report.*_report`）已可用且被脚本调用；CLI 接线是薄胶水（Spec §15 明确不提前做）。
- **接线前提**：**存在 VALID 基线**。当前 v2 基线 INVALID（C3 stable failure），`compare_run` 对 INVALID 基线恒 `REFUSE_COMPARE`——现在接线没有可用对象。
- **合理时机**：
  1. 若保持现状（C3 INVALID）→ **不接**（`--runs` + 纯函数已覆盖需求，README 说明即可）；
  2. 若未来重建出 VALID 基线（换模型复评 / P017 修复后）→ 同时接 `--establish-baseline`（基线落盘 `docs/evaluation/baselines/`）与 `--compare-baseline`（回归比较），作为**收口后的维护工具**；
  3. **面试版本可不接**——在 README 中如实标注「CLI 未接线，纯函数接口可用」。

## 6. 最终面试版本还缺的工程化内容

按重要性排序：

1. **merge_judge 6MB 修复或降级语义**（功能完整性，Q2/Q3 P0——若不做，写进 Known Limitations）；
2. **顶层项目 README**（当前根目录无面向读者/面试的「项目是什么 / 怎么跑 / 架构一页图 / 演示流程」）——第一印象最关键；
3. **启动/部署工程**：`backend/.env.example`（无密钥模板）、Neo4j 容器启动说明、一键 demo 脚本（上传《边城》→ 图渲染 walkthrough）；
4. **CI 骨架**（可选但加分）：pytest（unit+integration 分离）+ 提交即回归——展示测试纪律（TESTING.md 已有规范，缺执行载体）；
5. **Known Limitations 面试清单**（诚实清单：C3 extraction coverage / merge 6MB / 单次运行成本 / D-19 验收边界 / 语料锁《边城》）；
6. **前端完整性核对**（DESIGN.md 覆盖检查：上传 → job 轮询 → 图交互/搜索/状态展示）；
7. 可选：docker-compose 一键起全套（Neo4j + backend + frontend）。

## 7. 明确「不应该再做」的边界（防止无限扩张）

| 不做 | 依据 |
|---|---|
| 不引入 classifier 绕过 D5 | D-10（红线，永久） |
| 不扩 generic 词表（含 父亲/母亲/祖父/爹爹） | D-7（红线，永久） |
| 不修改 P16-b 冻结语义 / 不解除 D-6 | D-6（冻结） |
| **不为 baseline VALID 修改 C3 expectation** | 本轮用户明确；稳定失败不被冻结为正常 |
| 不做 extraction prompt B / 结构规则（P017 D5-a） | 本轮用户明确；cd52844 证据；无产品需求 |
| 不做性能优化专项（judge 串行等） | 用户约束（Q3 仅 P0 merge 例外） |
| 不新增 resume API / 前端入口 | P19 决策（重传即续跑） |
| 不引入 Redis / 持久化 JobStore 替代 checkpoint | D-14 / D-18 |
| 不做跨语料泛化（换小说需重新评估词表/分类/检查集） | D-7 / D-16 / P20 语料锁定哲学 |
| 不做无需求的模型探针 / 单次评估当结论 | P06 纪律 + 本轮明确 |
| 不新立 Problem 编号归档已有归因案例（A1/P021、C3→P017 D5-a） | D-12（同根因合并，不重复立项） |

---

*本路线图是规划文档；其中任何「未来可做」项在启动前仍需独立立项（Problem Record + Spec + Review，PROCESS.md §5）。*
