#!/usr/bin/env bash
# Serves the production build on port 3100. Run `npm run build` in frontend/ first.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d .next ] || npm run build
exec npx next start -p "${FRONTEND_PORT:-3100}"
