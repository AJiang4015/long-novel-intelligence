"""P19 checkpoint 层（纯 I/O，无业务决策）。

详见 CHECKPOINT_LAYER.md。
"""

from app.checkpoint.store import CHECKPOINT_SCHEMA_VERSION, CheckpointError, CheckpointStore

__all__ = ["CheckpointStore", "CheckpointError", "CHECKPOINT_SCHEMA_VERSION"]
