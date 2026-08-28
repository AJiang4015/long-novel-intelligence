# P20 Baseline Report — 《边城》（2026-08-28）

> **本报告是当前版本（git commit 见 Environment Baseline）的验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**

## 1. Baseline 元数据

- baseline_id: `biancheng-2026-08-28-deepseek-v4-flash-0731`；runs=['9e494d16-49c9-44af-a8d8-0c57a05a9cb1', 'a647a8ca-ebfe-4717-8f38-2393f68abe14', 'da86a5a0-4e3c-4fb8-bdd9-30c8ae743f75']
- checkset_version: 1；run_count: 3
- **baseline_status: `INVALID_NOT_REGRESSION_SAFE`**（存在 stable failure，禁止正常 REGRESSION 判定，Spec §7.3）
- compare_identity: corpus_hash=1293b0befe97… model=deepseek-v4-flash-0731 chunk=4000/400 chunker=1 extractor=1
- provenance（git_commit 仅记录，不参与 compare 兼容性）: {'git_commit': '2e7e47b6c3d350eaa31ccb54a403ef809b559550', 'git_dirty': False, 'model': 'deepseek-v4-flash-0731', 'concurrency': 4, 'neo4j_version': '5.26.0'}

## 2. per-check 分类（经验分类由 N 次运行决定性结果决定；初判仅展示先验）

| id | group | 经验分类 | satisfies_expected | outcome_distribution | 初判(先验) | attribution | layer |
|---|---|---|---|---|---|---|---|
| A1 | 正向合并 | stable | False | {'FAIL': 3} | variance | P08 / D-4 | merge |
| A2 | 正向合并 | variance | None | {'PASS': 2, 'FAIL': 1} | variance | P08 / D-4 | merge |
| A3 | 正向合并 | stable | True | {'PASS': 3} | stable | P08 / D-4 | merge |
| A4 | 正向合并 | stable | True | {'PASS': 3} | variance | P06 | judge |
| A5 | 正向合并 | stable | True | {'PASS': 3} | stable | P08 / D-4 | merge |
| A6 | 正向合并 | stable | True | {'PASS': 3} | variance | D-2 | registration |
| B1 | 非正文 | stable | True | {'PASS': 3} | stable | P016 | admission |
| B2 | 非正文 | unclassified | None | {'OBSERVATION': 3} | observation | P016 | admission |
| C1 | P16-b/P18 | stable | True | {'PASS': 3} | stable | D-5 / D-6 | admission |
| C2 | P16-b/P18 | stable | True | {'PASS': 3} | stable | D-5 | admission |
| C3 | P16-b/P18 | variance | None | {'FAIL': 2, 'PASS': 1} | variance | D-5 | admission |
| C4 | P16-b/P18 | stable | True | {'PASS': 3} | variance | D-6 / P018 | admission |
| C5 | P16-b/P18 | unclassified | None | {'OBSERVATION': 3} | observation | D-10 / P017-D5 | registration |
| D1 | P17/D-9 | stable | True | {'PASS': 3} | variance | P017 / D-9 | registration |
| D2 | P17/D-9 | unclassified | None | {'OBSERVATION': 3} | observation | P017 / P06 | registration |
| D3 | P17/D-9 | stable | True | {'PASS': 3} | stable | D-9 | registration |
| E1 | P09 | unclassified | None | {'OBSERVATION': 3} | observation | P09 | hygiene |
| F1 | merge | unclassified | None | {'OBSERVATION': 1, 'INCONCLUSIVE': 2} | observation | P11 | merge |
| G1 | 数据安全 | stable | True | {'PASS': 3} | stable | D-3 | db |
| G2 | 数据安全 | unclassified | None | {'OBSERVATION': 3} | observation | D-2 / TESTING.md §5 | db |
| G3 | 数据安全 | stable | True | {'PASS': 3} | stable | D-2 / D-3 | db |
| G4 | 数据安全 | unclassified | None | {'OBSERVATION': 3} | observation | P04 / P05 / P13 | infra |
| G5 | 数据安全 | stable | True | {'PASS': 3} | stable | P19（约束 1） | checkpoint |

## 3. stable failures（若存在）

- **A1**: {'FAIL': 3}（stable failure，基线 INVALID）

## 4. variance / unclassified 分布

- A2: {'PASS': 2, 'FAIL': 1}（variance）
- B2: {'OBSERVATION': 3}（unclassified）
- C3: {'FAIL': 2, 'PASS': 1}（variance）
- C5: {'OBSERVATION': 3}（unclassified）
- D2: {'OBSERVATION': 3}（unclassified）
- E1: {'OBSERVATION': 3}（unclassified）
- F1: {'OBSERVATION': 1, 'INCONCLUSIVE': 2}（unclassified）
- G2: {'OBSERVATION': 3}（unclassified）
- G4: {'OBSERVATION': 3}（unclassified）

## 5. quality 汇总

- stable_check_count=14 / stable_failure_count=1 / variance_check_count=2 / unclassified_check_count=7
## Run 溯源（novel_id 保留，TESTING.md §7）

- run=9e494d16-49c9-44af-a8d8-0c57a05a9cb1 novel_id=070c03ce-002d-40be-8099-3b90d0f9c3a9 job=completed persons=11 failed_blocks=0
- run=a647a8ca-ebfe-4717-8f38-2393f68abe14 novel_id=681538d9-5857-41bb-b432-39a127d4029b job=completed persons=29 failed_blocks=0
- run=da86a5a0-4e3c-4fb8-bdd9-30c8ae743f75 novel_id=40d057fb-52e0-409d-865f-fb3f8b27f032 job=completed persons=18 failed_blocks=0
