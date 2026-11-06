"""The storage interface used by every service.

The application implementation is ``WebHdfsClient``, which talks to a real cluster. The only other
implementation lives in ``tests/support`` and is a clearly labelled local-filesystem stand-in used by
fast unit tests. It is not importable from the application.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FileStatus:
    path: str
    is_dir: bool
    length: int
    replication: int
    block_size: int
    modification_time: int


@dataclass(frozen=True)
class ContentSummary:
    """Directly measured by the NameNode. ``space_consumed`` includes replication."""

    length: int
    space_consumed: int
    file_count: int
    directory_count: int


@dataclass(frozen=True)
class BlockLocation:
    block_id: int
    length: int
    hosts: tuple[str, ...]
    corrupt: bool


@runtime_checkable
class HdfsClient(Protocol):
    def mkdirs(self, path: str) -> None: ...

    def create(
        self,
        path: str,
        data: bytes | Iterable[bytes],
        *,
        length: int | None = None,
        overwrite: bool = False,
        replication: int | None = None,
    ) -> None: ...

    def open(self, path: str) -> Iterator[bytes]: ...

    def status(self, path: str) -> FileStatus | None: ...

    def list_dir(self, path: str) -> list[FileStatus]: ...

    def rename(self, source: str, destination: str) -> bool: ...

    def delete(self, path: str, *, recursive: bool = False) -> bool: ...

    def set_replication(self, path: str, factor: int) -> bool: ...

    def content_summary(self, path: str) -> ContentSummary: ...

    def block_locations(self, path: str) -> list[BlockLocation]: ...

    def default_replication(self) -> int: ...


def walk_files(client: HdfsClient, root: str) -> Iterator[FileStatus]:
    """Yield every file below ``root``. Missing roots yield nothing."""
    if client.status(root) is None:
        return
    stack = [root]
    while stack:
        for entry in client.list_dir(stack.pop()):
            if entry.is_dir:
                stack.append(entry.path)
            else:
                yield entry
