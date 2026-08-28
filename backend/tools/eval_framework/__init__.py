"""P20 Evaluation Framework —— 可重复 regression evaluation（Spec 2026-08-28-p020 v1.1）。

包定位：工具层（与 `tools/diagnose_lineage.py` / `tools/eval_p19_resume.py` 同级），
非 app 层、非 pytest 集成测试；真实 LLM 评估独立于 pytest（TESTING.md §3）。

模块：
- checks.py    checkset v1 声明式检查集 + 纯函数判定（Step 1）
- runner.py    编排（Step 2）：env 采集 / compare_identity / 上传 / 轮询 / 快照 / 检查
- evidence.py  alias→原文上下文证据转储（Step 2）
- baseline.py  基线聚合与回归比较（Step 3）
- report.py    TESTING.md §9 模板报告（Step 3）
"""
