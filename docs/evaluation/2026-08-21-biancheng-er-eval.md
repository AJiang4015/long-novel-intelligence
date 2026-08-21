# ER Evaluation Report —《边城》（2026-08-21）

## Symptom / Goal

- **Goal**：在全新独立 `novel-neo4j` 实例上，验证实体消歧（含同 chunk 共现召回）对《边城》零共享字称谓对（傩送↔二老、天保↔大老、老船夫↔爷爷）的合并效果。
- **Symptom**：上传与 ingest 全流程跑通（27 chunks → 70 人物 / 89 关系入库），但**基线人物几乎全部碎片化未合并**；23/27 个 chunk 存在失败块。

## Environment

- Git commit: `dab0900`（工作区含未提交 `.gitignore` 修改，非业务代码）
- Neo4j: **5.26.0 Community**（独立容器 `novel-neo4j`，VM 192.168.127.101:7687，卷 `novel_neo4j_data`，空库起步）
- Model: `qwen3.7-max-2026-05-17`（推理模型，响应含 `reasoning_content`）
- chunk_size / overlap / concurrency: **4000 / 400 / 4**
- Novel ID: **`517fe774-cb03-44af-a513-ffbc607156eb`**
- 后端：最新代码（含 co-occurrence 召回 + chunk 预扫描），未修改任何代码

## Before / After Statistics

| 指标 | 上传前 | 上传后 |
|---|---|---|
| Novel 节点 | 0 | 1 |
| Person | 0 | **70** |
| RELATES_TO | 0 | **89** |
| failed_blocks | – | **23**（27 chunks 中） |

## Canonical Examples（基线）

| 组 | 期望 | 实际 |
|---|---|---|
| 傩送 / 二老 / 老二 | 1 canonical | ❌ **碎片**：`傩送`、`二老`、`傩送二老`、`岳云二老`、`老二` 各自独立（aliases 均空） |
| 天保 / 大老 | 1 canonical | ❌ **碎片**：`天保`、`天保大人`、`天保大老`、`大老` 各自独立 |
| 老船夫 / 爷爷 / 祖父 | 1 canonical | ❌ **碎片**：`老船夫`(mc=9)、`祖父`(mc=12)、`爷爷`(mc=6) 三个独立节点 |
| 负向：傩送 vs 杨马兵 | 不合并 | ✅ 未合并（但为平凡通过——本次几乎无任何合并） |

## Alias Examples（成功合并的少数）

| canonical | aliases | 说明 |
|---|---|---|
| 母亲 | [妇人] | ✅ 合并成功 |
| 女孩子 | [小女孩] | ✅ 合并成功 |
| （其余 70 人中 aliases 大多为空） | | 合并率极低 |

## Failure Cases

`failed_blocks`（按 error 统计）：

| error | 数量 | 影响 |
|---|---|---|
| `alias_resolution_failed` | 13 | **judge 判定失败**（validation 或异常）→ 该 chunk 全部待判定 mention 独立成 canonical，**不尝试合并** |
| `unexpected:LLMError` | 6 | 抽取 4xx（非 429/5xx）→ 整 chunk 丢失 |
| `http_429` | 4 | 抽取限流（重试 1 次后仍 429）→ 整 chunk 丢失 |

仅约 4/27 chunk 抽取+判定双成功 → canonical 首现规则在大部分 chunk 无判定可依赖 → 碎片化。

## Root Cause（推断，证据待补）

1. **高频 429 限流**：concurrency=4 + 推理模型（qwen3.7-max 每调用含 reasoning，慢且占配额）→ 27 抽取 + 多轮 judge 调用在欠费充值后的默认限流下大量 429。
2. **judge 判定 13 次失败**：多为同源限流/超时；也可能是推理模型输出未通过 `AliasJudgeResult` 校验（validation error 不重试 → 直接失败）。
3. **`unexpected:LLMError`（6 次 4xx）**：非 429/5xx 的 4xx，具体状态码被 `extract_one` 泛化捕获丢失——需服务端日志/响应捕获才能定因。

## Known Limitations

- 判定失败（validation/限流）导致 chunk 待判定项**静默独立成 canonical**——是 V0.2 声明的预期副作用，但本次因失败面过大（13/27）成为主要碎片来源
- 推理模型 + 高并发下的限流敏感度：`LLM_CONCURRENCY=4` 过激进
- 抽取失败 chunk 整体丢失（无重试补救，重试仅 1 次）
- mention hygiene（`傩送二老` 畸形名）仍未处理（已明确留待下一步）

## 结论 / 下一步建议

- 管道端到端可用（上传→ingest→入库→查询），但本次 ER 质量被 LLM 失败淹没，**不能作为消歧能力结论**
- 建议按顺序尝试：
  1. **降低并发** `LLM_CONCURRENCY=1~2` 重跑（.env 配置变更，非代码）→ 验证限流消除后合并是否恢复
  2. 若仍失败：捕获 judge/抽取原始响应，定位 validation/4xx 具体原因（可能需要修 prompt 或重试策略——属代码变更，另行评估）
  3. 复跑后按 §4 基线重新导出对比
