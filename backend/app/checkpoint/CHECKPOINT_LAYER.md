# CHECKPOINT_LAYER.md — checkpoint 层契约与边界（P19）

> 定位：**Layer Contract / Layer Boundary**（本层负责什么、不能负责什么）。
> 全局架构见 `../../../ARCHITECTURE.md`；本层是 P19（Resumable Analysis）新增的可靠性基础设施层。

## 1. Responsibility

小说 ingest 的 **durable checkpoint 文件存储**（纯 I/O）：

- 按 `novel_id`（UUID）隔离的目录式文件存储：`manifest.json` / `chunks.jsonl` / `extraction/` / `judge/` / `merge_judge/`；
- 复合索引 `index.json`：`{content_hash}:{config_fingerprint} -> novel_id`（加速定位，可重建）；
- 原子写（tmp + `os.replace`）、路径防护、进程级锁（manifest/index read-modify-write）、损坏降级、写失败降级。

## 2. Input contract

| 操作 | 输入 |
|---|---|
| `put / get_exact / exists / delete / list_keys` | `novel_id`（UUID）+ 精确 key（`manifest` \| `chunks` \| `extraction/<chunk_id>` \| `judge/<chunk_id>/<fp>` \| `merge_judge/<fp>`）+ JSON 可序列化 dict |
| `save_manifest` | 完整 manifest dict（含 `novel_id` / `content_hash` / `config_fingerprint` / `status` 等，由 api 层构造） |
| `save_chunks` | chunk dict 列表（由 api 层从 `pipeline.chunker.Chunk` 序列化） |
| `save_extraction` | extraction payload（含 `status` / `attempts` / `config_fingerprint` / `result`） |
| `save_judge / save_merge_judge` | judge payload（含 version / input_fingerprint / result） |
| `find_manifest` | `content_hash` + `config_fingerprint`（64 位 hex） |

## 3. Output contract

- 全部读取返回**原样 dict**（不解释、不校验业务语义）；不存在 / 损坏 → `None`；
- 全部写入返回 `bool`（False = 写失败降级，**不抛异常**）；
- 路径 / 参数非法（非 UUID novel_id、非法 chunk_id、非法 fingerprint、未知 key）→ **抛 `CheckpointError`**（调用方 bug，非运行时降级）。

## 4. Decision ownership

**本层 owns**：

- 文件布局、原子写、路径防护、索引维护（复合键、重建）、损坏/写失败降级策略、novel 级清理。

**本层 does NOT own**：

- **「是否兼容」判定**（config_fingerprint / version / input_fingerprint 的比较归 api 层——CheckpointStore 只按精确键存取并原样返回，调用方自行比较）；
- COMPLETED 准入判定（「无 FAILED extraction + 无 judge 失败 + 无 merge 缺口 + 写库成功」归 api 层编排；`mark_complete` 只做状态写入）；
- extraction / resolver / merge 的任何语义（不解释 extraction 结果、不判定 canonical、不参与 ER 决策）。

## 5. Allowed dependencies

- stdlib（`json` / `os` / `re` / `shutil` / `threading` / `datetime` / `pathlib` / `logging`）。

## 6. Forbidden dependencies

- **不 import** pipeline / models / db / api（版本值、manifest 内容由 api 层构造后传入）；
- 不接触 Neo4j / HTTP / LLM。

## 7. Invariants

- `novel_id` 仅接受 UUID 格式（防路径穿越）；`chunk_id` 正整数；fingerprint 64 位 hex；
- 所有文件写入原子（tmp + rename），崩溃不产生半文件；
- 读取损坏文件 → 视为缺失（不崩溃、不抛异常）；
- 写失败 → 记日志 + 返回 False（**不中断 LLM 工作**——checkpoint 是可靠性增强，写失败降级到「该结果未 checkpoint」，绝不让 checkpoint 故障浪费已完成的 LLM 调用）；
- manifest 状态仅 `IN_PROGRESS / COMPLETED`（两态）；COMPLETED 由调用方判定后经 `mark_complete` 写入；
- index 是加速索引（非 source of truth），可随时 `rebuild_index()` 重建；
- 单进程线程安全（进程级锁）；**不支持多进程共享**（与 D-14 单进程部署哲学一致）。

## 8. Failure ownership

| 失败 | 归属 | 暴露方式 |
|---|---|---|
| 写失败（磁盘满 / 权限 / IO） | checkpoint（降级） | 日志 `[checkpoint] write failed` + 返回 False；job stats `checkpoint_warnings` 计数（api 层） |
| 读损坏 / 文件缺失 | checkpoint（降级） | 视为不存在（`None`）；该阶段 resume 时重跑 |
| 非法参数 / 路径穿越 | checkpoint（防御） | `CheckpointError`（调用方 bug） |
| index 丢失 / 不一致 | checkpoint（自愈） | `find_manifest` 回退全量扫描；`rebuild_index()` 修复 |

## 9. Testing expectations

- unit：`tests/unit/test_checkpoint_store.py`（全 mock / tmp_path，无网络、无 Neo4j）；
- 用例覆盖：round-trip、原子写、损坏降级、novel 隔离、index 并发与重建、多配置并存（AC-11）、路径防护、写失败降级、manifest 两态、`completed_extraction_ids` 指纹过滤、`load_extraction_results` 组装。

## 10. Typical changes allowed here

- 文件布局 / 原子写策略调整；
- 索引结构调整（须同步 `find_manifest` / `rebuild_index`）；
- 路径防护规则增补；
- 新增 checkpoint 文件类型（先经 P19 Spec 评审）。

## 11. Changes that must be implemented elsewhere

- 版本 / 指纹的兼容性判定、COMPLETED 准入、resume 编排：→ `api` 层（`../api/API_LAYER.md`）；
- 业务语义（extraction / resolver / merge）：→ `pipeline`（`../pipeline/PIPELINE_LAYER.md`）；
- job 状态机：→ `models`（`../models/MODEL_LAYER.md`）；
- Neo4j 读写：→ `db`（`../db/DB_LAYER.md`）。
