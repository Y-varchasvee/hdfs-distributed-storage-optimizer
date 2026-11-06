#!/usr/bin/env bash
# Rebuilds screenshots/ and evidence/ from a live system. Run with the backend and frontend running on an
# empty, freshly reset system (see scripts/reset-demo.sh). This stops and restarts HDFS containers on purpose.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"
mkdir -p evidence/restored screenshots

# 1. Use the application through a real browser: this fills the system and takes the page screenshots.
(cd frontend && npx playwright test -c capture/playwright.capture.config.ts --grep-invert "terminal evidence")
# 2. Record terminal output from the state the browser session left behind.
scripts/capture_terminal.sh
# 3. Render that output to images, unedited.
(cd frontend && npx playwright test -c capture/playwright.capture.config.ts --grep "terminal evidence")
rm -f evidence/.render.html
echo "Screenshots: screenshots/  Terminal logs: evidence/"
