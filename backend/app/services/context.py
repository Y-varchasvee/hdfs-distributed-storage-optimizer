"""Everything a service needs, passed explicitly so experiments and tests can use isolated instances."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.hdfs.base import HdfsClient


@dataclass(frozen=True)
class StoragePaths:
    """The internal HDFS namespace. Paths come from hashes and generated IDs, never from user input."""

    root: str

    @property
    def objects(self) -> str:
        return f"{self.root}/objects"

    @property
    def chunks(self) -> str:
        return f"{self.root}/chunks"

    @property
    def manifests(self) -> str:
        return f"{self.root}/manifests"

    @property
    def staging(self) -> str:
        return f"{self.root}/staging"

    @property
    def recovery(self) -> str:
        return f"{self.root}/recovery"

    @property
    def raw(self) -> str:
        return f"{self.root}/raw"

    def all_dirs(self) -> list[str]:
        return [self.objects, self.chunks, self.manifests, self.staging, self.recovery, self.raw]

    def object_path(self, sha256: str) -> str:
        return f"{self.objects}/{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def chunk_path(self, sha256: str) -> str:
        return f"{self.chunks}/{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def manifest_path(self, sha256: str, chunk_size: int) -> str:
        return f"{self.manifests}/{sha256[:2]}/{sha256}.{chunk_size}.json"

    def staging_path(self, token: str) -> str:
        return f"{self.staging}/{token}"

    def raw_path(self, file_id: str) -> str:
        return f"{self.raw}/{file_id[:2]}/{file_id}"

    def recovery_raw_path(self, file_id: str) -> str:
        return f"{self.recovery}/deleted/{file_id}"

    def recovery_orphan_path(self, name: str) -> str:
        return f"{self.recovery}/orphans/{name}"


@dataclass
class AppContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    hdfs: HdfsClient
    paths: StoragePaths
    monitor: Any = None  # ClusterMonitor; typed loosely to avoid a circular import
    jobs: Any = None  # JobManager
    # Guards content-addressed state so garbage collection can never race a new reference to the same
    # content. This assumes one API process, a limitation documented in the report.
    content_lock: threading.RLock = field(default_factory=threading.RLock)

    def ensure_namespace(self) -> None:
        for path in self.paths.all_dirs():
            self.hdfs.mkdirs(path)
