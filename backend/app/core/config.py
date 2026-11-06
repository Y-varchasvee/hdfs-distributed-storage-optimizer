"""Environment-based configuration. All values can be overridden with HDFSOPT_* variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

KIB = 1024
MIB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HDFSOPT_", env_file=".env", extra="ignore")

    # HDFS connection
    namenode_url: str = "http://127.0.0.1:9870"
    hdfs_user: str = "hadoop"
    # WebHDFS redirects name DataNodes by their container hostname. A backend running outside the
    # Docker network maps those names to published ports. Empty inside the Compose network.
    datanode_host_map: str = (
        "datanode1=127.0.0.1:19864,datanode2=127.0.0.1:19865,datanode3=127.0.0.1:19866"
    )
    root_path: str = "/hdfs-optimizer"
    http_timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 5.0

    # Local state
    database_path: Path = BACKEND_DIR / "data" / "metadata.db"
    dataset_dir: Path = PROJECT_DIR / "datasets" / "raw"
    provenance_path: Path = PROJECT_DIR / "datasets" / "provenance" / "manifest.json"
    spool_dir: Path = BACKEND_DIR / "data" / "spool"

    # API
    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"
    api_token: str | None = None  # when set, every mutating request must send X-API-Key
    max_upload_bytes: int = 2 * 1024 * MIB

    # Defaults that the settings page can change at runtime (see services/settings_store.py)
    default_ingest_mode: str = "file"
    default_chunk_size: int = 1 * MIB
    verify_on_write: bool = True

    # Limits
    min_chunk_size: int = 4 * KIB
    max_chunk_size: int = 64 * MIB

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def datanode_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for pair in self.datanode_host_map.split(","):
            if "=" in pair:
                name, target = pair.split("=", 1)
                mapping[name.strip()] = target.strip()
        return mapping

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
