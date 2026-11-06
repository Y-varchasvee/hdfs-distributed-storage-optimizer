"""Streaming SHA-256 and deterministic fixed-size chunking."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from pathlib import Path

BUFFER_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> tuple[str, int]:
    """Hash a local file with constant memory. Returns (hex digest, size in bytes)."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while block := handle.read(BUFFER_SIZE):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def sha256_stream(stream: Iterable[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for block in stream:
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def read_file_blocks(path: Path | str, block_size: int = BUFFER_SIZE) -> Iterator[bytes]:
    with open(path, "rb") as handle:
        while block := handle.read(block_size):
            yield block


def fixed_size_chunks(stream: Iterable[bytes], chunk_size: int) -> Iterator[bytes]:
    """Re-slice a byte stream into chunks of exactly ``chunk_size``, except possibly the last.

    The result depends only on the bytes and the chunk size, not on how the input stream was buffered.
    Memory use is bounded by one chunk plus one input block.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    pending = bytearray()
    for block in stream:
        pending += block
        while len(pending) >= chunk_size:
            yield bytes(pending[:chunk_size])
            del pending[:chunk_size]
    if pending:
        yield bytes(pending)
