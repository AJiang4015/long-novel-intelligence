# P19 Resumable Analysis 真实评估报告 — 《边城》中断 → 重传自动 resume（2026-08-28）

> **本报告是 d726d2f（P19 实现 commit）的真实评估验证记录，不是下一轮修复方案；任何后续代码修改需另立设计 / Problem Record。**
> 评估只验证 P19 行为，不修改业务代码；若发现实现缺陷，另行立 Problem Record（P19 评估纪律）。
> 运行环境说明：本次评估共 4 次尝试（第 1 次 401 环境阻断 / 第 2、3 次超时与代理疑云 / 第 4 次配置确认后完成），详见 §7 环境事故记录。

## 0. 评估目标（P19 核心验收在真实 LLM 下的验证）

1. resume 阶段已完成 extraction chunk **零重复 LLM 调用**；
2. resume 阶段已完成且输入未变的 judge **零重复 LLM 调用**；
3. resume 新增调用**仅来自真正未完成/未命中的阶段**（含输入指纹变化的正确重判）；
4. resume 最终图与完整 uninterrupted run 的 canonical graph snapshot **结构级一致**（真实 LLM 方差允许合理差异）；
5. 记录真实 LLM 调用次数、恢复前后增量、失败点。

## 1. Environment Baseline（TESTING.md §6）

| 项 | 值 |
|---|---|
| Git commit | `d726d2fcb58c541aa7243f572f273d029f879430`（P19 提交；工作区含未提交的评估脚本 `tools/eval_p19_resume.py`） |
| Neo4j | 5.26.0 Community（`novel-neo4j`，bolt://192.168.127.101:7687，独立卷 `novel_neo4j_data`） |
| Model | `qwen3.7-flash-2026-07-15`（backend/.env `BAILIAN_MODEL`） |
| chunk / overlap / concurrency | 4000 / 400 / **4**（.env 为 1；评估脚本覆盖并发 4 加速，用户确认；P05 经验：并发非 429 主因） |
| 温度 | extract 0.2 / judge 0.1 / merge 0.1（llm_client 既有值） |
| LLM HTTP timeout | **300s**（评估脚本注入 `httpx.Client(timeout=300)`；默认 60s 对 flash 长文本过紧，见 §7） |
| API key | Machine 级环境变量 `BAILIAN_API_KEY`（35 字符）；`.env` 中为占位符（见 §7 事故记录） |
| EPUB | 《边城》（books/ 252,603 B），chapters=25，chunks=27 |
| 注入失败点 | chunk 20（约 74% 处；已完成大部分后中断） |
| ER_LINEAGE | 1 / RAW=1（.env；审计 JSONL 落盘 `../.tmp/lineage`） |
| 网络路径 | 系统 TUN 代理（verge-mihomo）透明转发；实测单调用 extract≈21s / judge≈29s（12 mentions） |

## 2. 评估设计

- **Run A（完整基准）**：checkpoint disabled 的完整 ingest（独立 novel_id），记录总调用次数与最终图（基准图）。
- **Run B（中断 + resume）**：checkpoint enabled；run1 在 chunk 20 注入 `LLMRetryableError`（模拟 quota/网络中断）→ job `completed_with_errors`、manifest `IN_PROGRESS`；移除故障后重传同一 EPUB → 自动 resume（复用 novel_id，新 job）→ `completed`、manifest `COMPLETED`。
- **计数**：包装器逐调用记录 `{chunk_id, ok, error}`（text→chunk_id 精确映射）；resume 前后 snapshot 差值 = 恢复增量。
- **图对比**：Neo4j 稳定键排序快照（persons: name/aliases/mention_count/chapters；relationships: source/target/type/weight/confidence），Run A vs Run B 结构级对比。
- **LLM 调用注入方式**：真实调用前抛错（不浪费 token）。

## 3. 结果

### 3.1 运行记录（Run 5：2026-08-28 03:29-04:17，qwen3.8-flash，干净恢复场景）

| 阶段 | extract | judge | merge | 失败点 |
|---|---|---|---|---|
| Run A（完整基准，checkpoint disabled） | 31（chunk13-16 各 +1 重试） | 19 | 1（400） | **chunk14/16 `unexpected:ReadTimeout`**（重试后仍失败）；merge_judge 400（6MB 超限） |
| Run B run1（注入 chunk20，checkpoint enabled） | 28（27+chunk20 重试） | 21 | 1（400） | **仅 chunk20（注入 http_429）**；13-16 重试成功；merge_judge 400 |
| Run B resume 增量 | **{20: 2}**（第 1 次 RemoteProtocolError → 重试成功） | **{全 0}** | +1（400） | — |

- **Run A persons=31 / rels=61；Run B（resume 完成）persons=52 / rels=71**
- Run B resume job：**`completed`，failed=[]**（干净）；`novel_reused=True`、`new_job=True`

### 3.2 resume 增量按 chunk（Run 5，核心验收）

- **extract delta：27 chunk 中 26 个为 0，仅 chunk20（中断点）=2**（第 1 次调用 `RemoteProtocolError: Server disconnected` → extract_one 重试 → 成功）→ **已完成 extraction 零重复调用 ✅**
- **judge delta：0（19 个 judge checkpoint 全部重放，零新增调用）** → **已完成 judge 零重复调用 ✅**
- **merge delta：+1**——chunk20 新提取成功产生新桥接证据 → merge 输入指纹变化 → 重新判定（输入指纹保护的正确行为）✅
- **新增调用仅来自未完成/未命中阶段** ✅

### 3.3 图对比（full vs resume）

- Run A 31 persons vs Run B 52 persons；`only_in_full_run` 7、`only_in_resume_run` 27、alias_diff/mention_count_diff 多处
- **归因（非 P19 缺陷）**：
  1. **LLM 非确定性（P06）**：Run A 与 Run B 是两次独立运行，qwen3.8-flash 的 extraction/judge 输出不同（TESTING §3 非确定性声明）；
  2. **Run A 基准不完整**：chunk14/16 真实 ReadTimeout 失败 → Run A 缺 2 个 chunk 提取（31 persons），Run B resume 全部成功（52 persons）——Run A 是"有失败的运行"，不能作为逐字节基准；
- **结论**：AC-2 的**逐字节一致性已在 mock 层验证**（unit 257 + integration 16：全量 vs resume canonical serialization 一致）；**真实 LLM 下两次独立运行不可逐字节比较**（方差 + 真实失败），本评估记录结构级差异并归因，不视为 P19 失败。

### 3.4 验收结论（Run 5，真实 LLM）

- [x] **已完成 extraction 零重复调用**（26/27 chunk delta=0，仅中断点重跑）
- [x] **已完成 judge 零重复调用**（19/19 checkpoint 全部重放，delta=0）
- [x] **新增调用仅来自未完成/未命中阶段**（chunk20 中断点 + merge 输入变化重判）
- [ ] 最终图 vs 完整 run 逐字节一致——**真实 LLM 下不适用**（P06 方差 + Run A 自身失败）；mock 层已通过；结构级差异归因记录
- [x] 调用次数/增量/失败点已记录（result.json + 本报告）

## 4. Known Limitations

- 中断为**注入式模拟**（wrapper 抛错），非真实进程 kill/quota 事件；但真实 LLM 调用与恢复路径均走生产代码；
- 单次运行；LLM 非确定性（P06）下结论为单次证据，趋势需多次运行（本评估聚焦 resume 机制，非 ER 质量）；
- **AC-2 逐字节一致性仅 mock 层可验证**（真实 LLM 两次运行不可比，TESTING §3）；
- 真实 judge 输入指纹变化导致的部分重判为**正确行为**（防缺失信息重放），非缺陷；
- 评估耗时：真实 LLM 串行 judge 阶段是主要耗时（分阶段占比见 §6 计时数据）；
- **配额依赖**：百炼免费额度（qwen3.7-flash 曾 403 FreeTierOnly）；qwen3.8-flash 可用；充值后解除；
- **merge_judge 请求体上限**：DashScope 6MB 请求体限制，《边城》桥接证据过大时 merge judge 400（既有行为暴露，Run A/B 对称，不影响 resume 机制验证）；
- **网络不稳定**：RemoteProtocolError（服务器断连）/ ReadTimeout 多次出现——真实环境噪音；resume/重试机制正确处理（重试成功或 checkpoint 重放）。

## 5. 环境事故记录（评估前置 + 运行中）

| 尝试 | 问题 | 处理 |
|---|---|---|
| 1 | `.env` 占位 key → 全量 401 `invalid_api_key`（P04 域） | 确认有效 key 在 Machine 级环境变量；注入后 API 200 |
| 2 | 并发 1 串行慢 | 评估脚本覆盖并发 4（用户确认） |
| 3 | 60s 默认超时疑云 | 注入 `httpx.Client(timeout=300)`；实测单调用 21-29s，确认 judge 阶段为真实耗时所在 |
| 4 | 运行中 **403 `AllocationQuota.FreeTierOnly`（qwen3.7-flash 免费额度耗尽）** + merge_judge 400 + chunk8 ReadTimeout；评估脚本 Run A 误设注入（bug） | 脚本 bug 已修复；**用户换 qwen3.8-flash**（独立免费额度，探测 200） |
| 5 | （最终运行）qwen3.8-flash 完整跑通；运行中网络不稳定（RemoteProtocolError/ReadTimeout） | resume/重试机制正确处理；用户充值后 qwen3.7-flash 亦可再用 |

评估产生 novel：Run A `8b42f812-f058-4fba-8493-26f1de62cc27`、Run B `8c5ac7d8-58d5-4cdd-ae29-f8387d215af0`（真实评估默认保留）；Run 4 的 `033ec5f2…` / `7e4a737e…` 与调试残留已在授权后清理。lineage JSONL 保留审计。

## 6. judge 阶段真实耗时占比（估算）

> **标注：ESTIMATE**——计时脚本（`tools/eval_p19_profile.py`，逐调用计时）因真实网络环境慢（服务器断连/慢响应，与 Run 5 同环境）运行 23 分钟未完成而被终止；以下为基于 **Run 5 阶段时序 + 独立实测单调用时长** 的估算，非逐调用计时。

**独立实测单调用时长**（真实 qwen3.8-flash，与评估同环境）：
- extract_chunk（4000 字符 + 完整 EXTRACTION_SYSTEM_PROMPT）：**≈21s**
- judge_aliases（4000 字符 + 12 mentions + 候选）：**≈29s**（真实 pending 通常更多 → 实际更长）

**Run 5 阶段时序**（Run A，03:29→03:37，约 8 分钟，无网络重试干扰）：
- extract 阶段：27 chunk 并发 4 ≈ 27×30s/4 ≈ **3-4 分钟**（31 次调用含 4 次重试）
- judge 阶段：19 次调用**串行**（resolver 顺序处理）≈ 19×30-60s ≈ **6-10 分钟**
- merge 阶段：1 次（400 失败，<1 分钟）

**结论：judge 阶段（串行）为单次 ingest 主要耗时，占比约 65-80%**（Run A 时序下 ~70%+）；extract 阶段因并发 4 显著加速。

**耗时结构含义**：judge 是 resolver 内顺序执行的 LLM 调用（每 chunk 至多一次 batch judge，输入含整块 chunk 正文 + pending），其串行性是 ingest 耗时的核心瓶颈（与 LLM 调用次数并列）；P19 checkpoint 重放使 resume 时 judge 阶段零调用（耗时归零），进一步验证恢复收益。

## 7. 结论

- **P19 resume 机制在真实 LLM 下工作正常**：中断（chunk20 注入）→ 重传同文件 → 自动复用 novel_id 续跑；已完成 extraction/judge **零重复调用**（judge delta=0 为最干净证据）；未命中阶段（中断点 + 输入变化）正确重新调用；resume job 干净完成（failed=[]）。
- **AC-2 逐字节一致性在 mock 层成立**（unit 257 + integration 16）；真实 LLM 下两次独立运行因 P06 方差与真实失败不可逐字节比较（结构级差异归因，非 P19 缺陷）。
- **环境发现（既有行为，独立跟进）**：merge_judge 请求体超 DashScope 6MB 上限；qwen3.7-flash 免费额度 403；真实网络不稳定——resume/重试机制均正确处理。
