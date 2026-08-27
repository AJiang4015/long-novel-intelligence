"""CheckpointStore —— P19 可恢复分析的 durable checkpoint 文件存储（纯 I/O 层）。

层契约（见同目录 CHECKPOINT_LAYER.md）：
- 只做 checkpoint 文件的持久化 / 读取 / 删除 / 索引维护（纯 I/O）；
- 不做任何业务决策：不解释 extraction 语义、不做「是否兼容」判定；
  版本 / 指纹的兼容性比较由 api 层（orchestration）完成，本层只按精确键存取并原样返回 payload；
- 不 import pipeline / models / db / api；仅依赖 stdlib。

可靠性属性（Spec §4.7）：
- 原子写：tmp + os.replace，崩溃不产生半文件；
- 读损坏：JSON 解析失败 → 视为缺失（安全降级，不抛异常）；
- 写失败：记日志 + 返回 False（调用方按「该结果未 checkpoint」降级；绝不中断 LLM 工作）；
- 路径防护：novel_id 仅接受 UUID；chunk_id 正整数；fingerprint 64 位 hex；拒绝路径穿越；
- 并发：manifest / index 的 read-modify-write 由进程级锁保护（单进程部署前提，与 D-14 哲学一致）。
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path

logger = logging.getLogger("app.checkpoint")

CHECKPOINT_SCHEMA_VERSION = 1

# 目录 / 文件常量
INDEX_FILE = "index.json"
MANIFEST_KEY = "manifest"
CHUNKS_KEY = "chunks"
EXTRACTION_PREFIX = "extraction"
JUDGE_PREFIX = "judge"
MERGE_JUDGE_PREFIX = "merge_judge"

_KNOWN_TOP = {MANIFEST_KEY, CHUNKS_KEY, EXTRACTION_PREFIX, JUDGE_PREFIX, MERGE_JUDGE_PREFIX}
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_CHUNK_ID_RE = re.compile(r"^[1-9][0-9]*$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

MANIFEST_STATUSES = ("IN_PROGRESS", "COMPLETED")


class CheckpointError(Exception):
    """checkpoint 层错误（路径防护 / 参数校验失败）。"""


class CheckpointStore:
    """按 novel_id 隔离的文件 checkpoint 存储（单进程线程安全）。"""

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir)
        self._lock = threading.Lock()  # 保护 manifest / index 的 read-modify-write

    # ---------------------------------------------------------------- 校验
    @staticmethod
    def _validate_novel_id(novel_id: str) -> None:
        if not isinstance(novel_id, str) or not _UUID_RE.match(novel_id):
            raise CheckpointError(f"novel_id 必须是 UUID 格式: {novel_id!r}")

    @staticmethod
    def _validate_chunk_id(chunk_id: int) -> None:
        if isinstance(chunk_id, bool) or not isinstance(chunk_id, int) or not _CHUNK_ID_RE.match(str(chunk_id)):
            raise CheckpointError(f"chunk_id 必须是正整数: {chunk_id!r}")

    @staticmethod
    def _validate_fingerprint(fp: str) -> None:
        if not isinstance(fp, str) or not _FINGERPRINT_RE.match(fp):
            raise CheckpointError(f"fingerprint 必须是 64 位 hex: {fp!r}")

    def _validate_key(self, key: str) -> None:
        """key 格式：'manifest' | 'chunks' | 'extraction/<chunk_id>' | 'judge/<chunk_id>/<fp>' | 'merge_judge/<fp>'。"""
        if not isinstance(key, str):
            raise CheckpointError(f"key 必须是字符串: {key!r}")
        parts = key.split("/")
        if not parts or parts[0] not in _KNOWN_TOP:
            raise CheckpointError(f"未知的 key 顶层: {key!r}")
        if parts[0] in (MANIFEST_KEY, CHUNKS_KEY):
            if len(parts) != 1:
                raise CheckpointError(f"key 段数错误: {key!r}")
            return
        if parts[0] == EXTRACTION_PREFIX:
            if len(parts) != 2:
                raise CheckpointError(f"key 段数错误: {key!r}")
            self._validate_chunk_id(int(parts[1]))
            return
        if parts[0] == MERGE_JUDGE_PREFIX:
            if len(parts) != 2:
                raise CheckpointError(f"key 段数错误: {key!r}")
            self._validate_fingerprint(parts[1])
            return
        if parts[0] == JUDGE_PREFIX:
            if len(parts) != 3:
                raise CheckpointError(f"key 段数错误: {key!r}")
            self._validate_chunk_id(int(parts[1]))
            self._validate_fingerprint(parts[2])
            return

    # ---------------------------------------------------------------- 路径
    def _novel_dir(self, novel_id: str) -> Path:
        self._validate_novel_id(novel_id)
        return self._root / novel_id

    def _key_path(self, novel_id: str, key: str) -> Path:
        self._validate_key(key)
        return self._novel_dir(novel_id) / f"{key}.json"

    # ---------------------------------------------------------------- 原子 I/O
    @staticmethod
    def _atomic_write(path: Path, data: str) -> bool:
        """tmp + os.replace 原子写。失败：记日志 + 返回 False（不抛异常，调用方按未 checkpoint 降级）。"""
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)
            return True
        except Exception as exc:  # noqa: BLE001 —— 写失败必须降级而非中断 LLM 工作
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            logger.warning("[checkpoint] write failed path=%s error=%s", path, exc)
            return False

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        """缺失 / 损坏（JSON 解析失败 / 非 dict）→ None（安全降级，不抛异常）。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    # ---------------------------------------------------------------- 通用原语（精确键；不做兼容判定）
    def put(self, novel_id: str, key: str, payload: dict) -> bool:
        """写入（覆盖）一个 checkpoint 文件。返回是否写入成功（False = 写失败降级）。"""
        return self._atomic_write(self._key_path(novel_id, key), json.dumps(payload, ensure_ascii=False))

    def get_exact(self, novel_id: str, key: str) -> dict | None:
        """精确键读取。不存在 / 损坏 → None。"""
        return self._read_json(self._key_path(novel_id, key))

    def exists(self, novel_id: str, key: str) -> bool:
        return self._key_path(novel_id, key).is_file()

    def delete(self, novel_id: str, key: str) -> bool:
        try:
            self._key_path(novel_id, key).unlink(missing_ok=True)
            return True
        except OSError as exc:
            logger.warning("[checkpoint] delete failed key=%s error=%s", key, exc)
            return False

    def list_keys(self, novel_id: str, prefix: str = "") -> list[str]:
        """列出 novel 下匹配前缀的 key（无序；诊断 / 测试用）。"""
        novel_dir = self._novel_dir(novel_id)
        if not novel_dir.is_dir():
            return []
        out: list[str] = []
        for path in novel_dir.rglob("*.json"):
            rel = path.relative_to(novel_dir).as_posix()
            if rel.endswith(".json"):
                rel = rel[:-5]
            if rel.startswith(prefix):
                out.append(rel)
        return out

    # ---------------------------------------------------------------- manifest
    def load_manifest(self, novel_id: str) -> dict | None:
        return self.get_exact(novel_id, MANIFEST_KEY)

    def save_manifest(self, novel_id: str, manifest: dict) -> bool:
        """保存 manifest 并更新复合索引（进程锁内 read-modify-write）。"""
        self._validate_novel_id(novel_id)
        content_hash = manifest.get("content_hash")
        config_fp = manifest.get("config_fingerprint")
        if not isinstance(content_hash, str) or not _FINGERPRINT_RE.match(content_hash):
            raise CheckpointError("manifest.content_hash 必须是 64 位 hex")
        self._validate_fingerprint(config_fp)
        if manifest.get("novel_id") != novel_id:
            raise CheckpointError("manifest.novel_id 必须与目录 novel_id 一致")
        if manifest.get("status") not in MANIFEST_STATUSES:
            raise CheckpointError(f"manifest.status 必须是 {MANIFEST_STATUSES}")
        with self._lock:
            ok = self.put(novel_id, MANIFEST_KEY, manifest)
            if ok:
                self._index_set(novel_id, content_hash, config_fp)
        return ok

    # ---------------------------------------------------------------- chunks
    def save_chunks(self, novel_id: str, chunks: list[dict]) -> bool:
        """chunks.jsonl 原子写（每行一个 chunk dict）。"""
        self._validate_novel_id(novel_id)
        lines = "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)
        return self._atomic_write(self._novel_dir(novel_id) / "chunks.jsonl", lines + "\n")

    def load_chunks(self, novel_id: str) -> list[dict] | None:
        self._validate_novel_id(novel_id)
        path = self._novel_dir(novel_id) / "chunks.jsonl"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        chunks: list[dict] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                logger.warning("[checkpoint] corrupt chunk line in %s → treated as missing", path)
                return None  # 损坏 → 整体视为缺失（安全降级）
            if isinstance(obj, dict):
                chunks.append(obj)
        return chunks

    # ---------------------------------------------------------------- extraction
    def save_extraction(self, novel_id: str, chunk_id: int, payload: dict) -> bool:
        self._validate_chunk_id(chunk_id)
        return self.put(novel_id, f"{EXTRACTION_PREFIX}/{chunk_id}", payload)

    def load_extraction(self, novel_id: str, chunk_id: int) -> dict | None:
        self._validate_chunk_id(chunk_id)
        return self.get_exact(novel_id, f"{EXTRACTION_PREFIX}/{chunk_id}")

    def completed_extraction_ids(self, novel_id: str, config_fingerprint: str) -> set[int]:
        """COMPLETED 且 config_fingerprint 精确匹配的 chunk_id 集合（指纹由调用方传入比较）。"""
        self._validate_novel_id(novel_id)
        extraction_dir = self._novel_dir(novel_id) / EXTRACTION_PREFIX
        if not extraction_dir.is_dir():
            return set()
        out: set[int] = set()
        for path in extraction_dir.glob("*.json"):
            payload = self._read_json(path)
            if not payload:
                continue
            if payload.get("status") != "COMPLETED":
                continue
            if payload.get("config_fingerprint") != config_fingerprint:
                continue
            chunk_id = payload.get("chunk_id")
            if isinstance(chunk_id, int) and chunk_id > 0:
                out.add(chunk_id)
        return out

    def load_failed_chunks(self, novel_id: str) -> list[dict]:
        """全部 FAILED extraction 标记（含 attempts / error），按 chunk_id 升序。"""
        self._validate_novel_id(novel_id)
        extraction_dir = self._novel_dir(novel_id) / EXTRACTION_PREFIX
        if not extraction_dir.is_dir():
            return []
        out: list[dict] = []
        for path in extraction_dir.glob("*.json"):
            payload = self._read_json(path)
            if payload and payload.get("status") == "FAILED":
                out.append(payload)
        out.sort(key=lambda p: p.get("chunk_id", 0))
        return out

    def load_extraction_results(self, novel_id: str, chunks: list[dict],
                                config_fingerprint: str) -> list[tuple[dict, dict]]:
        """全部 COMPLETED extraction（指纹匹配）与对应 chunk 组装，按 chunk_id 升序。

        返回 [(chunk_dict, result_dict), ...]；result = extraction payload 的 result 字段。
        """
        done = self.completed_extraction_ids(novel_id, config_fingerprint)
        results: list[tuple[dict, dict]] = []
        for chunk in sorted(chunks, key=lambda c: c.get("chunk_id", 0)):
            cid = chunk.get("chunk_id")
            if cid not in done:
                continue
            payload = self.load_extraction(novel_id, cid)
            if payload and isinstance(payload.get("result"), dict):
                results.append((chunk, payload["result"]))
        return results

    # ---------------------------------------------------------------- judge
    def save_judge(self, novel_id: str, chunk_id: int, input_fingerprint: str, payload: dict) -> bool:
        self._validate_chunk_id(chunk_id)
        self._validate_fingerprint(input_fingerprint)
        return self.put(novel_id, f"{JUDGE_PREFIX}/{chunk_id}/{input_fingerprint}", payload)

    def load_judge(self, novel_id: str, chunk_id: int, input_fingerprint: str) -> dict | None:
        self._validate_chunk_id(chunk_id)
        self._validate_fingerprint(input_fingerprint)
        return self.get_exact(novel_id, f"{JUDGE_PREFIX}/{chunk_id}/{input_fingerprint}")

    # ---------------------------------------------------------------- merge judge
    def save_merge_judge(self, novel_id: str, input_fingerprint: str, payload: dict) -> bool:
        self._validate_fingerprint(input_fingerprint)
        return self.put(novel_id, f"{MERGE_JUDGE_PREFIX}/{input_fingerprint}", payload)

    def load_merge_judge(self, novel_id: str, input_fingerprint: str) -> dict | None:
        self._validate_fingerprint(input_fingerprint)
        return self.get_exact(novel_id, f"{MERGE_JUDGE_PREFIX}/{input_fingerprint}")

    # ---------------------------------------------------------------- 终态
    def mark_complete(self, novel_id: str, final_stats: dict) -> bool:
        """manifest → COMPLETED（COMPLETED 准入判定归调用方；本方法只做状态写入）。"""
        with self._lock:
            manifest = self.load_manifest(novel_id)
            if manifest is None:
                return False
            manifest["status"] = "COMPLETED"
            manifest["final_stats"] = final_stats
            manifest["updated_at"] = _now()
            return self.put(novel_id, MANIFEST_KEY, manifest)

    # ---------------------------------------------------------------- 索引（复合键 content_hash:config_fingerprint -> novel_id）
    def _index_path(self) -> Path:
        return self._root / INDEX_FILE

    def _index_set(self, novel_id: str, content_hash: str, config_fingerprint: str) -> None:
        """进程锁内调用：read-modify-write 复合索引。"""
        key = f"{content_hash}:{config_fingerprint}"
        index = self._read_json(self._index_path()) or {}
        index[key] = novel_id
        self._atomic_write(self._index_path(), json.dumps(index, ensure_ascii=False, sort_keys=True))

    def find_manifest(self, content_hash: str, config_fingerprint: str) -> dict | None:
        """复合索引优先；缺失 / 未命中回退全量扫描（content_hash + config_fingerprint 双条件）。

        多命中（同 key 多 manifest）→ 取 updated_at 最新者 + 日志警告。
        """
        if not isinstance(content_hash, str) or not _FINGERPRINT_RE.match(content_hash):
            raise CheckpointError("content_hash 必须是 64 位 hex")
        self._validate_fingerprint(config_fingerprint)
        key = f"{content_hash}:{config_fingerprint}"
        with self._lock:
            index = self._read_json(self._index_path())
        if index:
            novel_id = index.get(key)
            if isinstance(novel_id, str):
                manifest = self.load_manifest(novel_id)
                if manifest is not None and manifest.get("content_hash") == content_hash \
                        and manifest.get("config_fingerprint") == config_fingerprint:
                    return manifest
        # 回退：全量扫描（index 缺失 / 不一致 / 未命中）
        return self._scan_manifest(content_hash, config_fingerprint)

    def _scan_manifest(self, content_hash: str, config_fingerprint: str) -> dict | None:
        if not self._root.is_dir():
            return None
        hits: list[dict] = []
        for manifest_path in self._root.glob(f"*/{MANIFEST_KEY}.json"):
            manifest = self._read_json(manifest_path)
            if manifest is None:
                continue
            if manifest.get("content_hash") != content_hash:
                continue
            if manifest.get("config_fingerprint") != config_fingerprint:
                continue
            hits.append(manifest)
        if not hits:
            return None
        if len(hits) > 1:
            logger.warning("[checkpoint] 多 manifest 命中同 (content_hash, config_fingerprint)，取 updated_at 最新")
            hits.sort(key=lambda m: m.get("updated_at", ""))
        return hits[-1]

    def rebuild_index(self) -> int:
        """从全部 manifests 重建复合索引。返回索引条目数（写失败返回 0）。"""
        with self._lock:
            index: dict[str, str] = {}
            if self._root.is_dir():
                for manifest_path in self._root.glob(f"*/{MANIFEST_KEY}.json"):
                    manifest = self._read_json(manifest_path)
                    if manifest is None:
                        continue
                    ch = manifest.get("content_hash")
                    cf = manifest.get("config_fingerprint")
                    nid = manifest.get("novel_id")
                    if isinstance(ch, str) and isinstance(cf, str) and isinstance(nid, str) \
                            and _FINGERPRINT_RE.match(ch) and _FINGERPRINT_RE.match(cf):
                        index[f"{ch}:{cf}"] = nid
            ok = self._atomic_write(self._index_path(), json.dumps(index, ensure_ascii=False, sort_keys=True))
            return len(index) if ok else 0

    # ---------------------------------------------------------------- 清理
    def delete_novel(self, novel_id: str) -> bool:
        """删除整个 novel 的 checkpoint（含索引条目）。测试 / 未来删除功能用。"""
        self._validate_novel_id(novel_id)
        with self._lock:
            removed_index = False
            index = self._read_json(self._index_path())
            if index:
                stale = [k for k, v in index.items() if v == novel_id]
                if stale:
                    for k in stale:
                        del index[k]
                    self._atomic_write(self._index_path(), json.dumps(index, ensure_ascii=False, sort_keys=True))
                    removed_index = True
            try:
                shutil.rmtree(self._novel_dir(novel_id), ignore_errors=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[checkpoint] delete_novel failed novel_id=%s error=%s", novel_id, exc)
                return False
            return removed_index or not self._novel_dir(novel_id).exists()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
