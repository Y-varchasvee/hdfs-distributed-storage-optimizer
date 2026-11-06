"""Cluster health read from the NameNode's JMX servlet and fsck servlet. Nothing here is estimated."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import httpx

from app.core.errors import HdfsError, HdfsUnavailable


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ClusterMonitor:
    def __init__(self, namenode_url: str, *, user: str = "hadoop", timeout_seconds: float = 10.0):
        self.base_url = namenode_url.rstrip("/")
        self.user = user
        self._http = httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=3.0))

    def close(self) -> None:
        self._http.close()

    def _bean(self, name: str) -> dict:
        try:
            response = self._http.get(f"{self.base_url}/jmx", params={"qry": f"Hadoop:service=NameNode,name={name}"})
        except httpx.TransportError as exc:
            raise HdfsUnavailable(f"Cannot reach the NameNode at {self.base_url}: {exc}") from exc
        if not response.is_success:
            raise HdfsError(f"NameNode JMX returned {response.status_code} for {name}.")
        beans = response.json().get("beans", [])
        if not beans:
            raise HdfsError(f"NameNode JMX has no bean named {name}.")
        return beans[0]

    def status(self) -> dict:
        """Current cluster state. A down NameNode is a normal answer here, not an exception."""
        checked_at = _now_iso()
        try:
            fs = self._bean("FSNamesystem")
            state = self._bean("FSNamesystemState")
            info = self._bean("NameNodeInfo")
            nn_status = self._bean("NameNodeStatus")
        except HdfsError as exc:
            return {"reachable": False, "error": exc.message, "checked_at": checked_at, "namenode_url": self.base_url}

        safemode = bool(info.get("Safemode"))
        live = int(fs.get("NumLiveDataNodes", 0))
        dead = int(fs.get("NumDeadDataNodes", 0))
        under = int(fs.get("UnderReplicatedBlocks", 0))
        missing = int(fs.get("MissingBlocks", 0))
        corrupt = int(fs.get("CorruptBlocks", 0))
        problems = []
        if safemode:
            problems.append("The NameNode is in safe mode, so writes are refused.")
        if dead:
            problems.append("1 DataNode is dead." if dead == 1 else f"{dead} DataNodes are dead.")
        if missing:
            problems.append("1 block has no live replica." if missing == 1 else f"{missing} blocks have no live replica.")
        if corrupt:
            problems.append("1 block is corrupt." if corrupt == 1 else f"{corrupt} blocks are corrupt.")
        if under:
            problems.append("1 block is under-replicated." if under == 1 else f"{under} blocks are under-replicated.")
        if live == 0:
            problems.append("No DataNodes are live.")

        return {
            "reachable": True,
            "checked_at": checked_at,
            "namenode_url": self.base_url,
            "health": "healthy" if not problems else ("critical" if missing or live == 0 else "degraded"),
            "problems": problems,
            "namenode": {
                "state": nn_status.get("State"),
                "role": nn_status.get("NNRole"),
                "host_and_port": nn_status.get("HostAndPort"),
                "software_version": info.get("SoftwareVersion"),
                "cluster_id": info.get("ClusterId"),
                "block_pool_id": info.get("BlockPoolId"),
                "started_at": nn_status.get("LastHATransitionTime") or None,
                "fs_state": state.get("FSState"),
                "safemode": safemode,
                "safemode_message": info.get("Safemode") or None,
            },
            "capacity": {
                "total_bytes": int(fs.get("CapacityTotal", 0)),
                "used_bytes": int(fs.get("CapacityUsed", 0)),
                "remaining_bytes": int(fs.get("CapacityRemaining", 0)),
                "non_dfs_used_bytes": int(info.get("NonDfsUsedSpace", 0)),
            },
            "namespace": {
                "files_total": int(fs.get("FilesTotal", 0)),
                "blocks_total": int(fs.get("BlocksTotal", 0)),
                "under_replicated_blocks": under,
                "missing_blocks": missing,
                "corrupt_blocks": corrupt,
                "pending_replication_blocks": int(fs.get("PendingReplicationBlocks", 0)),
                "pending_deletion_blocks": int(fs.get("PendingDeletionBlocks", 0)),
                "excess_blocks": int(fs.get("ExcessBlocks", 0)),
            },
            "datanodes": {
                "live": live,
                "dead": dead,
                "stale": int(fs.get("StaleDataNodes", 0)),
                "decommissioning": int(fs.get("NumDecommissioningDataNodes", 0)),
            },
        }

    def nodes(self) -> dict:
        checked_at = _now_iso()
        info = self._bean("NameNodeInfo")
        nodes = []
        for state, field in (("live", "LiveNodes"), ("dead", "DeadNodes")):
            for name, node in json.loads(info.get(field) or "{}").items():
                nodes.append(
                    {
                        "name": name.split(":")[0],
                        "transfer_address": name,
                        "state": state,
                        "last_contact_seconds": node.get("lastContact"),
                        "capacity_bytes": node.get("capacity"),
                        "used_bytes": node.get("usedSpace") if state == "live" else None,
                        "remaining_bytes": node.get("remaining"),
                        "non_dfs_used_bytes": node.get("nonDfsUsedSpace"),
                        "blocks": node.get("numBlocks"),
                        "version": node.get("version"),
                        "admin_state": node.get("adminState"),
                        "rack": node.get("location"),
                    }
                )
        nodes.sort(key=lambda n: n["name"])
        return {"checked_at": checked_at, "nodes": nodes}

    def fsck(self, path: str) -> dict:
        """Run fsck through the NameNode's servlet and parse the summary it prints."""
        try:
            response = self._http.get(
                f"{self.base_url}/fsck", params={"ugi": self.user, "path": path}, timeout=60
            )
        except httpx.TransportError as exc:
            raise HdfsUnavailable(f"Cannot reach the NameNode at {self.base_url}: {exc}") from exc
        if not response.is_success:
            raise HdfsError(f"fsck returned {response.status_code}: {response.text[:300]}")
        return parse_fsck(response.text)


def parse_fsck(text: str) -> dict:
    def integer(pattern: str) -> int | None:
        match = re.search(pattern, text, flags=re.MULTILINE)
        return int(match.group(1)) if match else None

    average = re.search(r"Average block replication:\s+([\d.]+)", text)
    status = re.search(r"Status:\s+(\w+)", text)
    return {
        "status": status.group(1) if status else None,
        "total_files": integer(r"Total files:\s+(\d+)"),
        "total_blocks": integer(r"Total blocks \(validated\):\s+(\d+)"),
        "minimally_replicated_blocks": integer(r"Minimally replicated blocks:\s+(\d+)"),
        "over_replicated_blocks": integer(r"Over-replicated blocks:\s+(\d+)"),
        "under_replicated_blocks": integer(r"Under-replicated blocks:\s+(\d+)"),
        "mis_replicated_blocks": integer(r"Mis-replicated blocks:\s+(\d+)"),
        "default_replication": integer(r"Default replication factor:\s+(\d+)"),
        "average_block_replication": float(average.group(1)) if average else None,
        "missing_blocks": integer(r"Missing blocks:\s+(\d+)"),
        "corrupt_blocks": integer(r"Corrupt blocks:\s+(\d+)"),
        "missing_replicas": integer(r"Missing replicas:\s+(\d+)"),
        "datanodes": integer(r"Number of data-nodes:\s+(\d+)"),
    }
