"""Client for the Apache Hadoop WebHDFS REST API.

Reference: https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/WebHDFS.html
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.core.errors import (
    HdfsAlreadyExists,
    HdfsError,
    HdfsFileNotFound,
    HdfsUnavailable,
)
from app.hdfs.base import BlockLocation, ContentSummary, FileStatus

READ_BUFFER = 1024 * 1024


class WebHdfsClient:
    def __init__(
        self,
        namenode_url: str,
        *,
        user: str = "hadoop",
        datanode_map: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
        connect_timeout_seconds: float = 5.0,
    ):
        self.base_url = namenode_url.rstrip("/")
        self.user = user
        self.datanode_map = datanode_map or {}
        timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        limits = httpx.Limits(max_keepalive_connections=8, keepalive_expiry=15)
        self._http = httpx.Client(timeout=timeout, limits=limits, follow_redirects=False)

    def close(self) -> None:
        self._http.close()

    # -- request plumbing ------------------------------------------------------------------------

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            raise HdfsError(f"HDFS path must be absolute: {path!r}")
        return f"{self.base_url}/webhdfs/v1{quote(path)}"

    def _rewrite_datanode_url(self, location: str) -> str:
        """Map a redirect to a DataNode's container hostname onto its published port, if configured."""
        parts = urlsplit(location)
        target = self.datanode_map.get(parts.hostname or "")
        if target is None:
            return location
        return urlunsplit((parts.scheme, target, parts.path, parts.query, parts.fragment))

    def _request(self, method: str, path: str, op: str, **params) -> httpx.Response:
        query = {"op": op, "user.name": self.user, **{k: str(v) for k, v in params.items() if v is not None}}
        try:
            response = self._http.request(method, self._url(path), params=query)
        except httpx.TransportError as exc:
            raise HdfsUnavailable(f"Cannot reach the NameNode at {self.base_url}: {exc}") from exc
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, path: str) -> None:
        if response.is_success:
            return
        exception, message = "", response.text[:500]
        try:
            remote = response.json()["RemoteException"]
            exception, message = remote.get("exception", ""), remote.get("message", message)
        except (ValueError, KeyError):
            pass
        if response.status_code == 404 or exception == "FileNotFoundException":
            raise HdfsFileNotFound(f"Not found in HDFS: {path}")
        if exception in {"FileAlreadyExistsException", "AlreadyBeingCreatedException"}:
            raise HdfsAlreadyExists(f"Already exists in HDFS: {path}")
        if exception in {"SafeModeException", "RetriableException", "StandbyException"} or response.status_code == 503:
            raise HdfsUnavailable(f"HDFS is not accepting this request ({exception}): {message}")
        raise HdfsError(f"WebHDFS {exception or response.status_code} on {path}: {message}")

    def _redirect(self, method: str, path: str, op: str, **params) -> str:
        response = self._request(method, path, op, **params)
        if response.status_code not in (301, 302, 303, 307, 308):
            self._raise_for_status(response, path)
            raise HdfsError(f"WebHDFS {op} on {path} did not redirect to a DataNode")
        return self._rewrite_datanode_url(response.headers["location"])

    # -- filesystem operations -------------------------------------------------------------------

    def mkdirs(self, path: str) -> None:
        response = self._request("PUT", path, "MKDIRS")
        self._raise_for_status(response, path)

    def create(
        self,
        path: str,
        data: bytes | Iterable[bytes],
        *,
        length: int | None = None,
        overwrite: bool = False,
        replication: int | None = None,
    ) -> None:
        """Two-step WebHDFS create: ask the NameNode where to write, then send the bytes to that DataNode."""
        location = self._redirect(
            "PUT", path, "CREATE", overwrite=str(overwrite).lower(), replication=replication
        )
        headers = {"Content-Type": "application/octet-stream"}
        if length is not None:
            headers["Content-Length"] = str(length)
        try:
            response = self._http.put(location, content=data, headers=headers)
        except httpx.TransportError as exc:
            raise HdfsUnavailable(f"Lost contact with the DataNode writing {path}: {exc}") from exc
        self._raise_for_status(response, path)

    def open(self, path: str) -> Iterator[bytes]:
        location = self._redirect("GET", path, "OPEN", buffersize=READ_BUFFER)
        try:
            with self._http.stream("GET", location) as response:
                if not response.is_success:
                    response.read()
                    self._raise_for_status(response, path)
                yield from response.iter_bytes(READ_BUFFER)
        except httpx.TransportError as exc:
            raise HdfsUnavailable(f"Lost contact with the DataNode reading {path}: {exc}") from exc

    @staticmethod
    def _to_status(parent: str, raw: dict) -> FileStatus:
        suffix = raw.get("pathSuffix") or ""
        full = parent if not suffix else f"{parent.rstrip('/')}/{suffix}"
        return FileStatus(
            path=full,
            is_dir=raw["type"] == "DIRECTORY",
            length=int(raw.get("length", 0)),
            replication=int(raw.get("replication", 0)),
            block_size=int(raw.get("blockSize", 0)),
            modification_time=int(raw.get("modificationTime", 0)),
        )

    def status(self, path: str) -> FileStatus | None:
        response = self._request("GET", path, "GETFILESTATUS")
        if response.status_code == 404:
            return None
        self._raise_for_status(response, path)
        return self._to_status(path, response.json()["FileStatus"])

    def list_dir(self, path: str) -> list[FileStatus]:
        response = self._request("GET", path, "LISTSTATUS")
        self._raise_for_status(response, path)
        return [self._to_status(path, raw) for raw in response.json()["FileStatuses"]["FileStatus"]]

    def rename(self, source: str, destination: str) -> bool:
        response = self._request("PUT", source, "RENAME", destination=destination)
        self._raise_for_status(response, source)
        return bool(response.json()["boolean"])

    def delete(self, path: str, *, recursive: bool = False) -> bool:
        response = self._request("DELETE", path, "DELETE", recursive=str(recursive).lower())
        self._raise_for_status(response, path)
        return bool(response.json()["boolean"])

    def set_replication(self, path: str, factor: int) -> bool:
        response = self._request("PUT", path, "SETREPLICATION", replication=factor)
        self._raise_for_status(response, path)
        return bool(response.json()["boolean"])

    def content_summary(self, path: str) -> ContentSummary:
        response = self._request("GET", path, "GETCONTENTSUMMARY")
        self._raise_for_status(response, path)
        raw = response.json()["ContentSummary"]
        return ContentSummary(
            length=int(raw["length"]),
            space_consumed=int(raw["spaceConsumed"]),
            file_count=int(raw["fileCount"]),
            directory_count=int(raw["directoryCount"]),
        )

    def block_locations(self, path: str) -> list[BlockLocation]:
        response = self._request("GET", path, "GET_BLOCK_LOCATIONS")
        self._raise_for_status(response, path)
        blocks = response.json()["LocatedBlocks"].get("locatedBlocks", [])
        return [
            BlockLocation(
                block_id=int(entry["block"]["blockId"]),
                length=int(entry["block"]["numBytes"]),
                hosts=tuple(sorted(loc["hostName"] for loc in entry.get("locations", []))),
                corrupt=bool(entry.get("isCorrupt", False)),
            )
            for entry in blocks
        ]

    def default_replication(self) -> int:
        response = self._request("GET", "/", "GETSERVERDEFAULTS")
        self._raise_for_status(response, "/")
        return int(response.json()["FsServerDefaults"]["replication"])
