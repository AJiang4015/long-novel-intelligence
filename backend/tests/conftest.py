import os
import sys

# 手动解包依赖目录（沙箱环境 pip 不可用时用），须在导入 app 前注入
_DEPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".deps")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)

import pytest


def pytest_collection_modifyitems(config, items):
    """默认排除 integration 用例；显式 `pytest -m integration` 时才运行。"""
    marker_expr = config.getoption("markexpr") or ""
    if "integration" in marker_expr:
        return
    items[:] = [item for item in items if "integration" not in item.keywords]
