import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";

const stateDir = path.join(os.tmpdir(), "hdfs-optimizer-e2e");

// Browser tests drive the real frontend against a second backend instance with its own database and its
// own HDFS directory, so they exercise the real cluster without touching managed data.
export const E2E_BACKEND = "http://127.0.0.1:8199";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  globalTeardown: "./e2e/teardown.ts",
  use: {
    baseURL: "http://localhost:3100",
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: "off",
  },
  webServer: [
    {
      command: `rm -rf ${stateDir} && mkdir -p ${stateDir} && cd ../backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8199`,
      url: `${E2E_BACKEND}/api/v1/health`,
      reuseExistingServer: false,
      env: {
        HDFSOPT_ROOT_PATH: "/hdfs-optimizer-e2e",
        HDFSOPT_DATABASE_PATH: path.join(stateDir, "metadata.db"),
        HDFSOPT_SPOOL_DIR: path.join(stateDir, "spool"),
        HDFSOPT_CORS_ORIGINS: "http://localhost:3100",
      },
    },
    { command: "npm run start", url: "http://localhost:3100", reuseExistingServer: true },
  ],
});
