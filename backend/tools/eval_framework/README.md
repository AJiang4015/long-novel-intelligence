# P20 Evaluation Framework（`backend/tools/eval_framework/`）

将人工 Neo4j 验收固化为可重复执行的 regression evaluation（[P020](../../../docs/problems/P020-evaluation-framework.md) / [Spec v1.1](../../../docs/superpowers/specs/2026-08-28-p020-evaluation-framework-design.md)）。

## 定位与边界

- **工具层**：位于 `backend/tools/`（与 `diagnose_lineage.py` / `eval_p19_resume.py` 同级），**不是 app 层**；
- **非 pytest**：真实 LLM 评估与 pytest 分离（TESTING.md §3），pytest 永远全 mock；本包走 TestClient + 真实 Neo4j；
- **非 CI 门禁**：单次 ingest 真实 LLM 成本高，手动触发 + 基线比较；
- **不修改 `backend/app/*`**；P19 checkpoint 语义零改动（eval 强制 `er_checkpoint_enabled=False`，G5 守卫）；
- **判定唯一入口 = `checks.evaluate_checkset`**：runner 只采集事实，不实现任何判定逻辑。

## 模块

| 模块 | 职责 | 状态 |
|---|---|---|
| `checks.py` | checkset **v2**（24 条检查 A1-A7 + B-G，D-19 修订）+ 纯函数判定（PASS/FAIL/OBSERVATION/INCONCLUSIVE/SKIP；前置空洞防；G4 降级） | ✅ Step 1（v2 2026-08-28） |
| `runner.py` | 事实采集/编排（env / corpus / job / Neo4j 快照 / stats / evidence）；CLI：`--runs` / `--smoke` / `--dry-run` | ✅ Step 2（基线/比较 CLI 接线为后续步骤） |
| `evidence.py` | alias→原文上下文 确定性检索（零 LLM），供人工可解释性复核（P18 纪律） | ✅ Step 2 |
| `baseline.py` | N 运行聚合 → 经验分类 stable/variance → satisfies_expected → baseline_status → compare（REGRESSION / OBSERVATION / REFUSE_COMPARE） | ✅ Step 3（纯函数；CLI 接线为后续步骤） |
| `report.py` | TESTING.md §9 模板 markdown（run / baseline / compare + 强制声明） | ✅ Step 3（纯函数） |

## 用法

前置：`backend/.env` 配置齐全（BAILIAN_API_KEY / BAILIAN_URL / NEO4J_PASSWORD）；`novel-neo4j` 运行中；语料 `books/边城_(沈从文)_….epub`（checkset 钉死 content_hash，文件被改动即 REFUSE）。

```powershell
cd backend
# 前置校验（checkset / corpus hash / checkpoint 断言 / env 可采集项；不创建 app、不调 LLM）
python -u tools/eval_framework/runner.py --dry-run

# 骨架自检（mock LLM + 真实 Neo4j；自检 novel 按 AGENTS.md §3 自动清理）
python -u tools/eval_framework/runner.py --smoke

# 真实运行（每次全新 novel_id；results 落 .tmp/eval-framework/runs/{run_id}/result.json）
python -u tools/eval_framework/runner.py --runs 1 --tag <tag>
```

**基线建立与回归比较当前经纯函数接口使用**（`baseline.aggregate_runs` / `baseline.compare_run` + `report.*_report` 渲染）；`--establish-baseline` / `--compare-baseline` CLI 接线为后续集成步骤，不提前接入。

## 纪律（违反即偏离 Spec）

- **fresh novel**：eval 强制 `er_checkpoint_enabled=False`（既有开关，不改 P19 语义）；每 run 全新 novel_id（TESTING.md §3）；
- **判定唯一入口 checks**：runner 只采集；baseline/report 只聚合与渲染；任何判定逻辑不得塞进 runner；
- **修改检查期望 = 修改决策**（Spec §4.2）：checkset 的期望/分类/归因改动必须 bump `checkset_version` 或独立立项；P16/P17/P18 冻结语义（D-5/D-6/D-9/D-10/D-13/D-17）编码为 OBSERVATION 类检查，**不得以 FAIL 形式重开**；
- **stable/variance 描述结果稳定性，不描述 correctness**（Spec §4.3）；基线经验分类由 N 次实际决定性结果决定，**checkset 初判（outcome_class）仅展示不参与分类**；
- **INVALID 基线禁止正常 REGRESSION 判定**（Spec §7.3）；compare 兼容性唯一依据 = **compare_identity**（git_commit / git_dirty 仅 provenance，不拒绝跨 commit 比较）；
- **数据安全**：harness 只读 Neo4j + 自建 novel_id；smoke 自清；真实评估结果默认保留（TESTING.md §7）；清理走 dry-run + `db.delete_novel` 精确删除；
- 长任务 `python -u` + 后台任务（PROCESS.md 运行纪律）。

## 检查集 v2（24 条，Spec §4.2 + D-19 修订）

| 组 | 检查 | 来源 |
|---|---|---|
| A 正向合并 | A1 傩送/二老（核心 gate）；A2 天保/大老；A3 老船夫→祖父；A4 爷爷→祖父；A5 负向 傩送 vs 杨马兵；A6 alias 搜索；**A7 老二 吸收观察（D-19：单次低显著性 mention 不要求稳定覆盖，OBSERVATION 不判败）** | TESTING.md §4 / DECISIONS D-19 |
| B 非正文 | B1 非正文 canonical=0；B2 provisional 计数 | TESTING.md §9.1 / P016 |
| C P16-b/P18 | C1 父亲 拦截；C2 翠翠的父亲 拦截；C3 爹爹 confirmed；C4 sink 收敛；C5 爸爸 OBSERVATION（D5，记录不判败） | D-5 / D-6 / P018 |
| D P17/D-9 | D1 家族碎片收敛；D2 descriptive 计数；D3 碎片不注册 | P017 / D-9 |
| E P09 | E1 hygiene 过滤计数 | P09 |
| F merge | F1 merge 观察（全 failed → INCONCLUSIVE，非 FAIL） | P11 |
| G 数据安全 | G1 labels 白名单；G2 计数记录；G3 novel 隔离；G4 failed_blocks 记录+降级；G5 checkpoint 守卫 | D-3 / P19（约束 1） |

## 环境基线

**TESTING.md §6 是事实来源**：runner `_collect_env()` 逐项采集（git_commit / git_dirty / model / chunk_size / chunk_overlap / concurrency / neo4j_version / novel_id / checkpoint_enabled / llm_http_timeout）写入 result.env，缺失 → refuse。`compare_identity`（Spec §5.2：corpus_hash + checkset_version + model + chunk_size + chunk_overlap + chunker/extractor 版本 + prompt_hashes×3）与 P19 manifest 的 config_fingerprint 同哲学——**语义相关才作废**。

## 关系

| 文档 | 关系 |
|---|---|
| `TESTING.md` §4/§5/§9 | 检查期望来源 + 报告模板；数据库验收执行入口指向本包（§5） |
| `TESTING.md` §6 | 环境基线必填字段（harness 的事实来源） |
| `P020` Problem Record / Spec v1.1 | 本包设计依据（约束 / 判定分类 / compare 规则） |
| `PIPELINE_LAYER.md` §4 | 检查 attribution / layer 归因来源（六类归因链） |
