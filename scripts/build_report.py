#!/usr/bin/env python3
"""Generate report data from the repository, then compile the PDF with Typst.

The code listings, API table and schema all come from the working source, so the report cannot diverge from it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT / "reports" / "source"
GENERATED = SOURCE / "generated"
FINAL = PROJECT / "reports" / "final" / "HDFS_Storage_Optimizer_Complete_Report.pdf"
sys.path.insert(0, str(PROJECT / "backend"))

LANG = {".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".css": "css", ".yml": "yaml", ".sh": "bash", ".xml": "xml", ".json": "json", ".ini": "ini", ".mjs": "javascript", ".mako": "text", ".txt": "text", ".md": "markdown"}

GROUPS = [
    ("Infrastructure and deployment", ["docker-compose.yml", "docker-compose.light.yml", ".env.example", "infrastructure/docker/hadoop/Dockerfile", "infrastructure/docker/hadoop/entrypoint.sh", "infrastructure/hadoop/*.xml", "backend/Dockerfile", "backend/.dockerignore", "frontend/Dockerfile", "frontend/.dockerignore"]),
    ("Backend: core, models and HDFS client", ["backend/requirements*.txt", "backend/alembic.ini", "backend/pytest.ini", "backend/app/main.py", "backend/app/core/*.py", "backend/app/models/*.py", "backend/app/schemas/*.py", "backend/app/hdfs/*.py", "backend/migrations/env.py", "backend/migrations/script.py.mako", "backend/migrations/versions/*.py"]),
    ("Backend: deduplication and services", ["backend/app/services/*.py"]),
    ("Backend: API routes", ["backend/app/api/*.py"]),
    ("Frontend: libraries and shared components", ["frontend/package.json", "frontend/tsconfig.json", "frontend/next.config.ts", "frontend/eslint.config.mjs", "frontend/postcss.config.mjs", "frontend/components.json", "frontend/.env.example", "frontend/app/globals.css", "frontend/app/layout.tsx", "frontend/lib/*.ts", "frontend/components/*.tsx", "frontend/components/shell/*.tsx", "frontend/components/charts/*.tsx"]),
    ("Frontend: pages", ["frontend/app/page.tsx", "frontend/app/*/page.tsx"]),
    ("Tests", ["backend/tests/conftest.py", "backend/tests/support/*.py", "backend/tests/test_*.py", "frontend/playwright.config.ts", "frontend/e2e/*.ts", "frontend/capture/*.ts"]),
    ("Reproduction and tooling scripts", ["scripts/*.sh", "scripts/*.py", "presentation/source/prepare_crops.py", "presentation/source/build_deck.js", "presentation/source/package.json", "reports/source/requirements.txt"]),
]


def code_files() -> list[dict]:
    groups, seen = [], set()
    for title, patterns in GROUPS:
        files = []
        for pattern in patterns:
            for path in sorted(PROJECT.glob(pattern)):
                relative = path.relative_to(PROJECT).as_posix()
                if not path.is_file() or relative in seen or path.name == "__init__.py":
                    continue
                seen.add(relative)
                text = path.read_text()
                files.append({"path": relative, "lang": "dockerfile" if path.name == "Dockerfile" else LANG.get(path.suffix, "text"), "lines": text.count("\n") + 1})
        if files:
            groups.append({"title": title, "files": files})
    return groups


def api_routes() -> list[dict]:
    from app.main import create_app

    schema = create_app().openapi()
    routes = []
    for path, methods in schema["paths"].items():
        for method, spec in methods.items():
            description = (spec.get("description") or spec.get("summary") or "").strip().split("\n")[0]
            routes.append({"method": method.upper(), "path": path.removeprefix("/api/v1"), "summary": description})
    return routes


def db_schema() -> list[dict]:
    from app.core.db import Base
    from app.models import entities  # noqa: F401
    from sqlalchemy import CheckConstraint, UniqueConstraint

    tables = []
    for table in Base.metadata.sorted_tables:
        columns = []
        for column in table.columns:
            keys = []
            if column.primary_key:
                keys.append("primary key")
            keys.extend(f"references {fk.target_fullname}" for fk in column.foreign_keys)
            if column.unique:
                keys.append("unique")
            if column.index:
                keys.append("indexed")
            columns.append({"name": column.name, "type": str(column.type), "nullable": bool(column.nullable), "key": ", ".join(keys)})
        constraints = [c.name for c in table.constraints if isinstance(c, CheckConstraint | UniqueConstraint) and c.name]
        constraints += [i.name for i in table.indexes if i.name and i.name.startswith("uq_")]
        tables.append({"name": table.name, "columns": columns, "constraints": constraints})
    return tables


def test_counts() -> dict:
    def parse(name: str) -> dict:
        path = PROJECT / "evidence" / f"{name}.txt"
        text = path.read_text() if path.exists() else ""
        passed = re.findall(r"(\d+) passed", text)
        failed = re.findall(r"(\d+) failed", text)
        return {"passed": int(passed[-1]) if passed else 0, "failed": int(failed[-1]) if failed else 0}

    return {"unit": parse("07_unit_tests"), "integration": parse("08_integration_tests"), "browser": parse("09_browser_tests")}


def main() -> int:
    GENERATED.mkdir(parents=True, exist_ok=True)
    groups = code_files()
    (GENERATED / "code_files.json").write_text(json.dumps(groups, indent=1))
    (GENERATED / "api_routes.json").write_text(json.dumps(api_routes(), indent=1))
    (GENERATED / "db_schema.json").write_text(json.dumps(db_schema(), indent=1))
    (GENERATED / "test_counts.json").write_text(json.dumps(test_counts(), indent=1))
    print("source listing:", sum(len(g["files"]) for g in groups), "files,", sum(f["lines"] for g in groups for f in g["files"]), "lines")
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["typst", "compile", "--root", str(PROJECT), str(SOURCE / "main.typ"), str(FINAL)])
    if result.returncode:
        return result.returncode
    print(f"wrote {FINAL} ({FINAL.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
