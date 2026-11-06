#!/usr/bin/env bash
# Captures real command output into evidence/*.txt, with each command shown above its output.
# Run while the application and HDFS are running, after the UI capture has populated the system.
set -uo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"
mkdir -p evidence

run() {
  # run <file> <command...>: append the command line and its unedited output.
  local file="evidence/$1.txt"; shift
  { printf '$ %s\n' "$*"; "$@" 2>&1; printf '[exit code %s]\n\n' "$?"; } >> "$file"
}
start() { : > "evidence/$1.txt"; printf '# Captured %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "evidence/$1.txt"; }

start 01_docker_cluster
run 01_docker_cluster docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.State}}\t{{.Health}}\t{{.Ports}}'
run 01_docker_cluster docker compose exec -T namenode hadoop version
run 01_docker_cluster docker info --format '{{.OperatingSystem}} {{.Architecture}} CPUs={{.NCPU}} MemBytes={{.MemTotal}}'

start 02_hdfs_report
run 02_hdfs_report docker compose exec -T namenode hdfs dfsadmin -report

start 03_hdfs_namespace
run 03_hdfs_namespace docker compose exec -T namenode hdfs dfs -ls /hdfs-optimizer
run 03_hdfs_namespace docker compose exec -T namenode hdfs dfs -count -q -h /hdfs-optimizer
run 03_hdfs_namespace docker compose exec -T namenode hdfs dfs -du -s -h /hdfs-optimizer/objects /hdfs-optimizer/chunks /hdfs-optimizer/manifests /hdfs-optimizer/raw
run 03_hdfs_namespace docker compose exec -T namenode bash -c 'hdfs dfs -ls -R /hdfs-optimizer/chunks | grep "^-" | head -8'

start 04_hdfs_fsck
run 04_hdfs_fsck docker compose exec -T namenode bash -c 'hdfs fsck /hdfs-optimizer 2>/dev/null | grep -A16 "^Status"; hdfs fsck /hdfs-optimizer 2>/dev/null | tail -2'
run 04_hdfs_fsck docker compose exec -T namenode bash -c 'F=$(hdfs dfs -ls -R /hdfs-optimizer/chunks | grep "^-" | head -1 | awk "{print \$NF}"); hdfs fsck "$F" -files -blocks -locations 2>/dev/null | head -8'

start 05_backend_execution
run 05_backend_execution curl -s http://127.0.0.1:8100/api/v1/health
run 05_backend_execution curl -s http://127.0.0.1:8100/api/v1/storage/savings --output /dev/null -w 'HTTP %{http_code} in %{time_total}s\n'
run 05_backend_execution python3 -c "import json,urllib.request as u; d=json.load(u.urlopen('http://127.0.0.1:8100/api/v1/storage/statistics')); print(json.dumps(d['derived'],indent=1)); print(json.dumps({k:d['measured'][k] for k in ('length','space_consumed','file_count','directory_count')},indent=1))"
run 05_backend_execution tail -n 12 backend/data/backend.log

start 06_restore_checksum
if [ -f evidence/restored/same-book-renamed.html ]; then
  run 06_restore_checksum shasum -a 256 datasets/raw/originals/pg1342.html evidence/restored/same-book-renamed.html
  run 06_restore_checksum cmp datasets/raw/originals/pg1342.html evidence/restored/same-book-renamed.html
fi
run 06_restore_checksum python3 -c "import json;m=json.load(open('datasets/provenance/manifest.json'));print([f['sha256'] for f in m['files'] if f['local_path']=='originals/pg1342.html'][0], 'recorded in provenance manifest')"

start 07_unit_tests
(cd backend && { printf '$ pytest -m "not hdfs" -v\n'; .venv/bin/python -m pytest -m "not hdfs" -q 2>&1 | tail -6; printf '\n'; }) >> evidence/07_unit_tests.txt

start 08_integration_tests
(cd backend && { printf '$ pytest -m hdfs -v  (real HDFS cluster)\n'; .venv/bin/python -m pytest -m hdfs -v 2>&1 | grep -E "PASSED|FAILED|ERROR|SKIPPED|passed|failed" | sed 's/tests\/test_integration_hdfs.py:://'; printf '\n'; }) >> evidence/08_integration_tests.txt

start 09_browser_tests
(cd frontend && { printf '$ npx playwright test  (real browser, real cluster)\n'; npx playwright test 2>&1 | grep -vE "WebServer|^$" ; printf '\n'; }) >> evidence/09_browser_tests.txt

start 10_dataset_provenance
run 10_dataset_provenance python3 -c "import json;m=json.load(open('datasets/provenance/manifest.json'));print('files:',m['number_of_files'],'originals:',m['number_of_original_files'],'bytes:',m['total_size_bytes']);[print(f['kind'][:5],f['file_format'].ljust(4),str(f['size_bytes']).rjust(9),f['sha256'][:16],f['local_path']) for f in m['files']]"
echo "Terminal evidence written to evidence/"

# Keep the replication timings from this session as machine-readable evidence.
python3 - <<'PY'
import json, urllib.request
from datetime import datetime
operations = json.load(urllib.request.urlopen("http://127.0.0.1:8100/api/v1/cluster/replication"))["operations"]
for op in operations:
    start, end = op["requested_at"], op["completed_at"]
    op["duration_seconds"] = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() if end else None
json.dump(operations, open("benchmarks/results/replication_operations.json", "w"), indent=2, default=str)
print("replication operations:", [(o["requested_factor"], o["status"], o["duration_seconds"]) for o in operations])
PY
