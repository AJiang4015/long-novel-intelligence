# PROBLEM.md — 问题知识库（症状 → 根因 → 做法 → 预防）

> 用途：Agent 遇到类似现象时，能快速判断「先查什么、不做什么、怎么处理」。
> 维护规则与记录标准见 `AGENTS.md` §10（只记高价值问题，不记 typo/一眼可见错误）。
> 状态：✅ resolved ｜ 🔍 investigating。

---

## 0. Do / Don't（高频踩坑速查）

### Do

- 删除数据一律 `db.delete_novel(novel_id)`（按 id 精确；删除前 dry-run 列目标）
- 每个测试用例创建独立 `novel_id`，结束后只清理自己的
- `EntityResolver` 一次 ingest 一个实例（`known`/mention index 整本持续）
- 长任务脚本用 `python -u`（无缓冲）+ 后台任务方式运行
- 真实评估前记录 Environment Baseline（commit/model/chunk/concurrency/novel_id/Neo4j 版本）
- 修改 `resolver.py` 后跑 `test_resolver.py` 回归清单（TESTING.md §8）
- LLM 报错先看诊断日志 `[llm] stage=... status=... code=...`（区分 Arrearage/限流/validation）
- 改 `.env` 后必须重启后端（settings 进程内缓存）

### Don't

- 不执行全库 DELETE / DETACH DELETE（含 `MATCH (n:Novel) DELETE n`）
- 不跨 novel_id 查询或清理 Person
- 不在 diagnose 模式修改代码/数据/配置
- 不依赖「数据库初始为空」
- 不把一次真实 LLM 评估当成 deterministic 测试
- 不把 LLM 非确定性（judge 判定、提取输出）当确定性结果写死进测试

---

## 按域索引

| 域 | 条目 | 状态 |
|---|---|---|
| Neo4j 数据安全 | P01 全库删除事故｜P02 共享实例 | ✅ ✅ |
| 测试与流程 | P03 计划测试与实现语义互斥 | ✅ |
| LLM / API 行为 | P04 账号欠费｜P05 限流｜P06 judge 非确定性｜P07 4xx 被吞 | ✅ ✅ 🔍 ✅ |
| ER 算法 | P08 零共享字称谓未合并｜P09 垃圾别名 hygiene｜P10 共现顺序敏感｜P11 全失败应为 failed | 🔍 🔍 ✅ 🔍 |
| 环境与沙箱 | P12 沙箱限制清单｜P13 脚本超时丢输出 | ✅ ✅ |
| 基础设施（防复发） | P14 依赖/驱动 API 坑汇总 | ✅ |

---

## 1. Neo4j 数据安全

### P01 测试全库删除 Novel → 孤儿数据事故

- **症状**: 一次集成测试运行后，真实 Novel 节点全部消失，残留 329 孤儿 Person + 577 条 RELATES_TO
- **根因**: 测试为断言「空列表」执行 `MATCH (n:Novel) DELETE n`；只删 Novel 不删 Person/边
- **错误做法**: 测试里做无范围 destructive 清理
- **正确做法**: 删除一律 `db.delete_novel(novel_id)`；测试用独立 novel_id 自建自清；「空列表」用非破坏性结构断言
- **以后遇到类似问题**: 任何测试/脚本先检查是否存在无 novel_id 范围的 DELETE；见到 `MATCH (n) DELETE n` 一律拒绝
- **Status**: ✅ resolved
- **Git commit**: `a534116`（含实例迁移）；规则入 TESTING.md §1/§8

### P02 共享 Neo4j 实例混入其他业务数据

- **症状**: 小说项目连接的 Neo4j 含约 4.8 万医疗图谱节点（疾病/药品/食物/…），全局操作可能波及他人数据
- **根因**: VM 上 python-project compose 栈与小说项目共用 7474/7687
- **错误做法**: 直接连共享实例跑项目
- **正确做法**: 独立 `novel-neo4j`（novel-project compose，卷 `novel_neo4j_data`）；共享栈已停用且 `restart=no`
- **以后遇到类似问题**: 先确认目标实例是 novel-neo4j（空库/只含 Novel/Person/RELATES_TO）；禁止触碰其他标签
- **Status**: ✅ resolved
- **Git commit**: `a534116`

---

## 2. 测试与流程

### P03 计划测试与实现语义互斥（流程教训）

- **症状**: 计划中 3 个 resolver 测试与「known 整本持续」语义矛盾，任何实现都无法同时通过
- **根因**: 写计划时测试断言与既定语义（alias 写 known → 缓存命中）未对齐
- **错误做法**: 为通过测试而削弱行为断言
- **正确做法**: 以 spec 语义为准修订测试（不削弱断言）；评审拦截计划级矛盾
- **以后遇到类似问题**: 新测试先对照既有语义锁（TESTING.md §8 回归清单）；多测试互斥时先查语义而非改实现
- **Status**: ✅ resolved
- **Git commit**: `f3baf2a`

---

## 3. LLM / API 行为

### P04 百炼账号欠费（Arrearage）

- **症状**: 全部 LLM 调用返回 400 `code=Arrearage`「overdue-payment」；充值后可能再次复现
- **根因**: 阿里云百炼账号余额/欠费状态（跨模型均 400，与模型名无关）
- **错误做法**: 当成代码 bug 排查
- **正确做法**: 单次探测确认（任一模型应 200）；区分 `Arrearage` vs `limit_requests` vs validation
- **以后遇到类似问题**: 先看 `[llm]` 诊断日志的 `code` 字段；Arrearage 是账号问题，找用户充值，不改代码
- **Status**: ✅ resolved（账号层）
- **Git commit**: `36e8019`（诊断日志）

### P05 429 限流（limit_requests）

- **症状**: `code=limit_requests`；并发 4 时 27 chunk 大面积失败；并发 1 后 0 失败
- **根因**: 推理模型（qwen3.7-max-preview）慢且占配额；高并发触发账号限流
- **错误做法**: 默认 `LLM_CONCURRENCY=4` 跑真实 ingest
- **正确做法**: 真实评估用 `LLM_CONCURRENCY=1`；429 重试 1 次 + 退避
- **以后遇到类似问题**: 真实 ingest 报 429 先降并发，再考虑重试策略
- **Status**: ✅ resolved（配置层）
- **Git commit**: 配置变更（.env，未提交）

### P06 judge 判定非确定性 + 过度合并

- **症状**: 同一 chunk 同一候选集，不同运行 judge 判「相同」或「不同」；且会把泛指词（水上人/轻薄男子）误并入人物
- **根因**: LLM 判定概率性（temperature 0.1 仍波动）；judge prompt 对「称谓 vs 本名」「泛指 vs 人名」约束不足
- **错误做法**: 假设 judge 结果可复现；把单次 judge 输出当 ground truth
- **正确做法**: 评估多次取趋势；记录 Environment Baseline 以解释差异；测试用 mock judge
- **以后遇到类似问题**: 消歧结果差异先怀疑 judge 非确定性（对照诊断日志），再怀疑算法
- **Status**: 🔍 investigating
- **Git commit**: `685d019`（评估报告）/ `36e8019`（日志）

### P07 LLM 4xx 状态码被吞

- **症状**: failed_blocks 只有 `unexpected:LLMError`，无法区分 400/401/403
- **根因**: `extract_one` 把 `LLMError` 当通用异常捕获，丢失状态码
- **错误做法**: 用异常类型猜原因
- **正确做法**: `llm_client` 记录 `[llm] stage=... status=... body=...`（不含 key）
- **以后遇到类似问题**: 先看 `[llm]` 日志的 status/code 再定位
- **Status**: ✅ resolved
- **Git commit**: `36e8019`

---

## 4. ER 算法 / 消歧

### P08 零共享字称谓对未合并（二老↔傩送、天保↔大老）

- **症状**: 《边城》中 二老/傩送、天保/大老 各自独立 canonical（{二,老} vs {傩,送} 零共享字）
- **根因**: ① 两成员首次同 chunk 共现时都未知 → 互不为候选；② 提取变异性使「本名」很少与「称谓」同 chunk 被提取（天保 本体罕见与 大老 同现，只有 天保大老 桥接名）；③ judge 判定非确定性（重放证明 二老→傩送 可合并，原运行判不同）
- **错误做法**: 仅靠「提取输出的人名」做共现召回；假设 judge 稳定
- **正确做法（待定方向）**: 文本层共现召回（用 chunk 原文中的已知 canonical 作候选，绕开提取变异性）；judge 一致性/质量改进；桥接名传播
- **以后遇到类似问题**: 消歧失败先分「确定性机制缺口」（重放可复现）vs「judge 非确定性」（重放分歧）
- **Status**: 🔍 investigating
- **Git commit**: `685d019`（稳定性评估）/ 诊断重放（未提交代码）

### P09 `傩送二老` 垃圾别名（mention hygiene）

- **症状**: 提取 LLM 输出畸形人物名（如「傩送二老」），被 ER 吸收为别名或独立 canonical
- **根因**: 提取层畸形输出 + judge 契约无「无效 mention 丢弃」选项（只能 resolves_to 或 null）
- **错误做法**: 让 ER 忠实吸收提取层垃圾
- **正确做法（待定）**: judge 契约增加 drop 选项 / 提取层约束
- **Status**: 🔍 investigating

### P10 同 chunk 共现召回顺序敏感

- **症状**: 未知 mention 出现在已知名之前时丢失共现候选（top-5 被字符重合占满）
- **根因**: `confirmed` 从空集随处理顺序累积
- **错误做法**: 假设共现与处理顺序无关
- **正确做法**: chunk 预扫描——处理前把本 chunk 中已知名预置进 `confirmed`
- **以后遇到类似问题**: 顺序相关行为先查「状态累积时机」而非召回公式
- **Status**: ✅ resolved
- **Git commit**: `c850bda`

### P11 全部 chunk 失败时 job 状态应为 failed

- **症状**: 27/27 chunk 失败时 job 仍为 `completed_with_errors`；spec §5.1 定义「全部失败 → failed」
- **根因**: `_run_ingest` 只按 failed_blocks 非空判 `completed_with_errors`；`failed` 仅在异常路径设置
- **错误做法**: 以「有数据输出」倒推状态正确
- **正确做法（待定）**: 终态判定补「全部 chunk 失败 → failed」（代码变更未授权）
- **Status**: 🔍 investigating

---

## 5. 环境与沙箱

### P12 沙箱/环境限制清单

- **症状**: ① pip 装不了依赖（wheel 解包 Permission denied）；② pytest `tmp_path`/basetemp 目录被锁；③ vite build `spawn EPERM`（exec "net use"）
- **根因**: 沙箱拦截长进程创建目录后的读写/删除；禁管道 stdio spawn
- **错误做法**: 反复重试 pip；在测试里依赖 tmp_path
- **正确做法**: 依赖手动解包 `backend/.deps`（conftest 注入）；`epub_factory` 用 BytesIO 不落盘；pytest 禁缓存 + 唯一 basetemp；vite 本地 node_modules 补丁（重装后需重打）
- **以后遇到类似问题**: 沙箱内先走「工作区内目录 + 无管道 spawn」路径；改 `.env` 后重启后端（settings 进程内缓存）
- **Status**: ✅ resolved（环境特定）
- **Git commit**: `3267755` 系

### P13 轮询脚本被工具超时杀 + stdout 缓冲丢输出

- **症状**: 长轮询脚本被工具 10 分钟超时终止，已打印的 novel_id/job_id 因 stdout 缓冲丢失
- **根因**: python stdout 非 tty 时缓冲；工具超时强杀进程
- **错误做法**: 长任务前台跑 + 依赖 stdout 回显
- **正确做法**: `python -u` + 后台任务；后端 ingest 是后台任务，脚本被杀不影响后端
- **Status**: ✅（经验）

---

## 6. 基础设施缺陷（已修，防复发）

### P14 依赖/驱动 API 坑汇总

| 坑 | 根因 | 修法 | commit |
|---|---|---|---|
| llm_client 缺 Authorization 头 | 计划代码缺陷，`_api_key` 未用 | POST 补 Bearer 头 + 单测 | `8c25836` |
| `get_subgraph` ResultConsumedError | `session.run()` 结果在 `with session` 外迭代 | `list(session.run(...))` 会话内物化 | `dcf6023` |
| Neo4j 属性不支持 map | 属性值仅允许原始类型/数组 | chapters/evidence JSON 序列化存储 | `dcf6023` |
| ebooklib 0.20 无 `get_title` | 依赖 API 变化 | `getattr(item,"title","")` | `f2b03c6` |
