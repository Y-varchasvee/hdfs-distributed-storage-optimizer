import { defineConfig } from "@playwright/test";

// Used only by scripts/capture_evidence.sh, against the running application.
export default defineConfig({
  testDir: ".",
  testMatch: "capture.spec.ts",
  timeout: 360_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  outputDir: "../test-results/capture",
  use: { baseURL: "http://localhost:3100", channel: "chrome", headless: true, acceptDownloads: true },
});
