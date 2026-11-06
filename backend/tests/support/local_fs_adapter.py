"""TEST ONLY. A local-filesystem stand-in for HDFS, used by fast unit tests.

This is NOT HDFS and is never used by the application: it lives outside the ``app`` package. Behaviour
that depends on real HDFS is covered by ``test_integration_hdfs.py`` against the real cluster.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path

from app.core.errors import HdfsAlreadyExists, HdfsFileNotFound, HdfsUnavailable
from app.hdfs.base import BlockLocation, ContentSummary, FileStatus


class LocalFsTestAdapter:
    """Mimics the HDFS semantics services rely on, such as rename refusing to overwrite."""

    def __init__(self, base: Path, default_replication: int = 3):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)
        self.replication: dict[str, int] = {}
        self._default_replication = default_replication

    def _local(self, path: str) -> Path:
        return self.base / path.lstrip("/")

    def mkdirs(self, path: str) -> None:
        self._local(path).mkdir(parents=True, exist_ok=True)

    def create(self, path, data, *, length=None, overwrite=False, replication=None) -> None:
        target = self._local(path)
        if target.exists() and not overwrite:
            raise HdfsAlreadyExists(f"Already exists: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as handle:
            for block in [data] if isinstance(data, bytes) else data:
                handle.write(block)
        self.replication[path] = replication or self._default_replication

    def open(self, path: str) -> Iterator[bytes]:
        target = self._local(path)
        if not target.is_file():
            raise HdfsFileNotFound(f"Not found: {path}")
        with open(target, "rb") as handle:
            while block := handle.read(64 * 1024):
                yield block

    def _status(self, path: str, target: Path) -> FileStatus:
        return FileStatus(
            path=path,
            is_dir=target.is_dir(),
            length=0 if target.is_dir() else target.stat().st_size,
            replication=0 if target.is_dir() else self.replication.get(path, self._default_replication),
            block_size=134217728,
            modification_time=int(target.stat().st_mtime * 1000),
        )

    def status(self, path: str) -> FileStatus | None:
        target = self._local(path)
        return self._status(path, target) if target.exists() else None

    def list_dir(self, path: str) -> list[FileStatus]:
        target = self._local(path)
        if not target.is_dir():
            raise HdfsFileNotFound(f"Not found: {path}")
        return [self._status(f"{path.rstrip('/')}/{entry.name}", entry) for entry in sorted(target.iterdir())]

    def rename(self, source: str, destination: str) -> bool:
        src, dst = self._local(source), self._local(destination)
        if not src.exists() or dst.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        if source in self.replication:
            self.replication[destination] = self.replication.pop(source)
        return True

    def delete(self, path: str, *, recursive: bool = False) -> bool:
        target = self._local(path)
        if not target.exists():
            return False
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        self.replication.pop(path, None)
        return True

    def set_replication(self, path: str, factor: int) -> bool:
        if not self._local(path).is_file():
            return False
        self.replication[path] = factor
        return True

    def _walk(self, path: str) -> Iterable[tuple[str, Path]]:
        root = self._local(path)
        if not root.exists():
            raise HdfsFileNotFound(f"Not found: {path}")
        for entry in root.rglob("*"):
            if entry.is_file():
                yield "/" + str(entry.relative_to(self.base)), entry

    def content_summary(self, path: str) -> ContentSummary:
        length = consumed = files = 0
        for logical, entry in self._walk(path):
            size = entry.stat().st_size
            length += size
            consumed += size * self.replication.get(logical, self._default_replication)
            files += 1
        directories = sum(1 for entry in self._local(path).rglob("*") if entry.is_dir()) + 1
        return ContentSummary(length=length, space_consumed=consumed, file_count=files, directory_count=directories)

    def block_locations(self, path: str) -> list[BlockLocation]:
        size = self._local(path).stat().st_size
        hosts = tuple(f"fake-dn{i}" for i in range(self.replication.get(path, self._default_replication)))
        return [BlockLocation(block_id=1, length=size, hosts=hosts, corrupt=False)]

    def default_replication(self) -> int:
        return self._default_replication


class FaultInjector:
    """Wraps an adapter and fails the Nth call to a chosen method, simulating a crash or outage."""

    def __init__(self, inner, *, method: str, on_call: int = 1, error: Exception | None = None):
        self._inner = inner
        self._method = method
        self._remaining = on_call
        self._error = error or HdfsUnavailable("Injected outage")
        self.armed = True

    def __getattr__(self, name):
        attribute = getattr(self._inner, name)
        if name != self._method:
            return attribute

        def wrapper(*args, **kwargs):
            if self.armed:
                self._remaining -= 1
                if self._remaining == 0:
                    self.armed = False
                    raise self._error
            return attribute(*args, **kwargs)

        return wrapper


class FakeMonitor:
    """TEST ONLY. Stands in for the NameNode's JMX and fsck servlets."""

    def __init__(self, hdfs: LocalFsTestAdapter, *, live: int = 3, reachable: bool = True):
        self.hdfs = hdfs
        self.live = live
        self.reachable = reachable

    def status(self) -> dict:
        if not self.reachable:
            return {"reachable": False, "error": "Injected outage", "checked_at": "now", "namenode_url": "fake"}
        return {
            "reachable": True,
            "checked_at": "now",
            "namenode_url": "fake",
            "health": "healthy",
            "problems": [],
            "namenode": {"state": "active", "software_version": "fake", "safemode": False},
            "capacity": {"total_bytes": 1000, "used_bytes": 0, "remaining_bytes": 1000, "non_dfs_used_bytes": 0},
            "namespace": {
                "files_total": 0,
                "blocks_total": 0,
                "under_replicated_blocks": 0,
                "missing_blocks": 0,
                "corrupt_blocks": 0,
                "pending_replication_blocks": 0,
                "pending_deletion_blocks": 0,
                "excess_blocks": 0,
            },
            "datanodes": {"live": self.live, "dead": 0, "stale": 0, "decommissioning": 0},
        }

    def nodes(self) -> dict:
        return {"checked_at": "now", "nodes": []}

    def fsck(self, path: str) -> dict:
        factors = list(self.hdfs.replication.values())
        return {
            "status": "HEALTHY",
            "total_files": len(factors),
            "total_blocks": len(factors),
            "over_replicated_blocks": 0,
            "under_replicated_blocks": 0,
            "missing_blocks": 0,
            "corrupt_blocks": 0,
            "average_block_replication": sum(factors) / len(factors) if factors else 0.0,
            "default_replication": self.hdfs.default_replication(),
        }
