# ER Stability Evaluation —《边城》并发 1（2026-08-21）

## Symptom / Goal

- **Goal**：验证 LLM 稳定性（`LLM_CONCURRENCY=1`）下完整 ingest 与 ER 质量；消除此前 429/欠费造成的碎片化。
- **Symptom**：并发 1 + 账号充值后，**零 LLM 错误**（无 429、无 4xx），27 chunks 全成功，82 人物 / 148 关系入库；ER 合并显著改善（老船夫/爷爷/祖父 合并成功），但零共享字对（傩送↔二老、天保↔大老）仍未合并。

## Environment

- Git commit: `36e8019`（仅 llm_client 诊断日志；Resolver 等 ER 代码未动）
- Neo4j: 5.26.0 Community（独立 `novel-neo4j`，空库起步）
- Model: **`qwen3.7-max-preview`**（`.env` 当前值）
- chunk_size / overlap / concurrency: **4000 / 400 / 1**
- Novel ID: **`3d782d98-b1a0-488b-8521-6743b4036051`**
- LLM 诊断：`[llm] stage=…` 日志启用（error 时输出 stage/status/body 摘要，不含 key）

## LLM 稳定性

| 指标 | 值 |
|---|---|
| total chunks | 27 |
| extract success / failure | **27 / 0** |
| judge success / failure | **全部成功**（0 条 `stage=judge` 错误日志） |
| 429 数量 | **0** |
| 4xx 数量 | **0** |
| failed_blocks | **0**（依据：零 `[llm]` 错误日志；job_id 因轮询脚本被工具超时终止而丢失，无法取原始 job 对象，但日志侧零失败为强证据） |

> 结论：**LLM 稳定性问题由账号欠费 + 高并发限流共同导致；并发 1 + 正常账号下 LLM 完全稳定。**

## Before / After Statistics

| 指标 | 上传前 | 上传后 |
|---|---|---|
| Novel | 0 | 1 |
| Person | 0 | **82**（14 个带 aliases，共 29 条别名） |
| RELATES_TO | 0 | **148** |
| failed_blocks | – | 0 |

## Canonical / Alias Examples

| canonical | aliases | 说明 |
|---|---|---|
| 祖父 (mc=21) | [老人, 老船夫, 爸爸, 爷爷] | ✅ **老船夫/爷爷/老人 全部合并**（基线组 3 通过） |
| 顺顺 (mc=16) | [顺顺大哥, 顺顺船总, 船总顺顺, 爹爹] | ✅ 合并 |
| 二老 (mc=11) | [岳云二老, 老二, 年青人] | ⚠️ 自身合并成功，但与 傩送 未合并 |
| 傩送 (mc=10) | [傩送二老] | ⚠️ 独立 canonical（且含垃圾别名 傩送二老） |
| 天保 | [天保大人] | ⚠️ 与大老 未合并 |
| 大老 | [天保大老] | ⚠️ 独立 |
| 杨马兵 | [马兵, 老马兵] | ✅ 负向组通过（与 傩送 等不合并） |

## Failure Cases

- **LLM 层：无**（0 失败）
- **ER 层（非 LLM 失败，属算法限制）**：
  1. `傩送` ↔ `二老`：零共享字（{傩,送} vs {二,老}），未合并——依赖同 chunk 共现 + LLM 判定；本次二者成为两个 canonical 后缓存命中，不再复判
  2. `天保` ↔ `大老`：同上
  3. `傩送二老` 垃圾别名仍进入 傩送.aliases（mention hygiene 未做，已知待办）

## Known Limitations

- 零共享字称谓对（二老=傩送、大老=天保）合并仍不稳定：需要「同 chunk 共现 + LLM 判定为同一人」同时成立，且首现规则下先出现的名定 canonical（本次为 二老/大老）
- `傩送二老` 畸形名 hygiene 未处理（下一步）
- canonical 首现规则可能选中称谓而非真名（如 二老 而非 傩送）——设计声明的权衡
