/**
 * Captures the execution evidence by really using the running application, from an empty system.
 * Nothing is mocked or edited: every image shows the live page at that moment.
 * Run through scripts/capture_evidence.sh, which resets demo data first.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, writeFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const ROOT = path.resolve(__dirname, "../..");
const SHOTS = path.join(ROOT, "screenshots");
const EVIDENCE = path.join(ROOT, "evidence");
const DATASET = path.join(ROOT, "datasets/raw");
const API = "http://localhost:8100/api/v1";

mkdirSync(SHOTS, { recursive: true });

const compose = (...args: string[]) => execFileSync("docker", ["compose", ...args], { cwd: ROOT, stdio: "pipe" });

async function shot(page: Page, name: string, fullPage = true) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(350); // let charts and transitions finish
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
}

async function jmx(): Promise<Record<string, number> | null> {
  try {
    const response = await fetch("http://127.0.0.1:9870/jmx?qry=Hadoop:service=NameNode,name=FSNamesystem");
    return (await response.json()).beans[0];
  } catch {
    return null;
  }
}

async function waitUntil(check: () => Promise<boolean>, seconds: number, what: string) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`Timed out waiting for ${what}`);
}

test.describe.serial("evidence", () => {
  test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });

  test("empty system", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("No files are managed yet")).toBeVisible();
    await shot(page, "00_dashboard_empty");
  });

  test("dataset provenance and ingestion", async ({ page }) => {
    await page.goto("/lab");
    await expect(page.getByText("Authentic original").first()).toBeVisible();
    await shot(page, "17_dataset_provenance");

    // Ingest all plain-text originals with two labelled workload copies each, without deduplication.
    const rows = page.locator("tbody tr").filter({ hasText: "Authentic original" }).filter({ has: page.locator('td:has-text("txt")') });
    const count = await rows.count();
    expect(count).toBe(9);
    for (let i = 0; i < count; i += 1) await rows.nth(i).getByRole("checkbox").check();
    await page.getByRole("button", { name: /Ingest 9 into HDFS/ }).click();
    await page.getByLabel("Exact workload copies per file").fill("2");
    await page.screenshot({ path: path.join(SHOTS, "12a_dataset_ingest_dialog.png") });
    await page.getByRole("dialog").getByRole("button", { name: "Ingest" }).click();
    await expect(page.getByText("dataset ingest finished.")).toBeVisible({ timeout: 120_000 });
  });

  test("file upload shows real outcomes", async ({ page }) => {
    await page.goto("/files");
    await page.getByRole("combobox", { name: "Storage mode for new uploads" }).click();
    await page.getByRole("option", { name: "Whole-file dedup" }).click();
    const html = readFileSync(path.join(DATASET, "originals/pg1342.html"));
    await page.getByTestId("file-input").setInputFiles({ name: "pride-and-prejudice.html", mimeType: "text/html", buffer: html });
    await expect(page.getByText("New content stored")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("file-input").setInputFiles({ name: "same-book-renamed.html", mimeType: "text/html", buffer: html });
    await expect(page.getByText("Duplicate: no new data stored")).toBeVisible({ timeout: 60_000 });
    await shot(page, "02_file_upload", false);
    await shot(page, "03_file_explorer");
  });

  test("file details, block locations, verification and restored checksum", async ({ page }) => {
    await page.goto("/files");
    await page.getByRole("button", { name: "same-book-renamed.html" }).click();
    await page.getByRole("button", { name: "Verify integrity" }).click();
    await expect(page.getByText("SHA-256 matches")).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SHOTS, "16a_file_details_verified.png") });

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: "Download" }).click();
    const download = await downloadPromise;
    const target = path.join(EVIDENCE, "restored", "same-book-renamed.html");
    await download.saveAs(target);
  });

  test("duplicate analysis", async ({ page }) => {
    await page.goto("/duplicates");
    await expect(page.getByRole("img", { name: /logical files share SHA-256/ }).first()).toBeVisible();
    await shot(page, "04_duplicate_analysis");
  });

  test("dry run, then optimization, then before and after", async ({ page }) => {
    await page.goto("/optimize");
    await page.getByRole("button", { name: "Run dry-run analysis" }).click();
    await expect(page.getByText("Nothing has changed yet.")).toBeVisible({ timeout: 60_000 });
    await shot(page, "05_optimization_preview");

    await page.getByRole("button", { name: "Start optimization" }).click();
    await page.screenshot({ path: path.join(SHOTS, "05a_optimization_confirm.png") });
    await page.getByRole("dialog").getByRole("button", { name: "Start optimization" }).click();
    await expect(page.getByText("Results below are observed, not predicted.")).toBeVisible({ timeout: 120_000 });
    await page.getByRole("button", { name: "Verify all restored bytes" }).click();
    await expect(page.getByText(/files match their SHA-256/)).toBeVisible({ timeout: 120_000 });
    await shot(page, "06_optimization_complete");
  });

  test("chunk-level sharing on documented partial overlap", async ({ page }) => {
    await page.goto("/files");
    await page.getByRole("combobox", { name: "Storage mode for new uploads" }).click();
    await page.getByRole("option", { name: "Chunk-level dedup" }).click();
    await page.getByRole("combobox", { name: "Chunk size" }).click();
    await page.getByRole("option", { name: "64 KiB" }).click();
    const files = ["originals/pg1661.html", "originals/pg11.epub"];
    for (const name of ["truncate_90", "replace_mid_byte", "prefix_newline"]) files.push(`workload/pg1342.${name}.txt`);
    await page.getByTestId("file-input").setInputFiles(
      files.map((file) => ({ name: path.basename(file), mimeType: "application/octet-stream", buffer: readFileSync(path.join(DATASET, file)) })),
    );
    await expect(page.getByText(/written/)).toHaveCount(5, { timeout: 120_000 });
    // Convert everything to chunks at the same size, so the original book and its variants can share chunks.
    await page.goto("/optimize");
    await page.getByRole("button", { name: "Chunk-level" }).click();
    await page.getByRole("combobox", { name: "Chunk size" }).click();
    await page.getByRole("option", { name: "64 KiB" }).click();
    await page.getByRole("button", { name: "Run dry-run analysis" }).click();
    await expect(page.getByText("Nothing has changed yet.")).toBeVisible({ timeout: 120_000 });
    await shot(page, "05b_chunk_preview");
    await page.getByRole("button", { name: "Start optimization" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Start optimization" }).click();
    await expect(page.getByText("Results below are observed, not predicted.")).toBeVisible({ timeout: 300_000 });
    await shot(page, "06b_chunk_complete");

    await page.goto("/duplicates");
    await page.getByRole("tab", { name: "Shared chunks" }).click();
    await expect(page.getByText("Chunk map")).toBeVisible();
    await shot(page, "04b_shared_chunks");
  });

  test("replication change, for real, down and back up", async ({ page }) => {
    test.setTimeout(900_000);
    await page.goto("/replication");
    await expect(page.getByRole("button", { name: "Increase replication factor" })).toBeDisabled();
    await page.getByRole("button", { name: "Decrease replication factor" }).click();
    await page.getByRole("button", { name: "Apply factor 2" }).click();
    await expect(page.getByRole("dialog")).toContainText("reduces fault tolerance");
    await page.screenshot({ path: path.join(SHOTS, "08a_replication_confirm.png") });
    await page.getByRole("dialog").getByRole("button", { name: "Lower to 2" }).click();
    await expect(page.getByRole("cell", { name: "3 to 2" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Verified").first()).toBeVisible({ timeout: 300_000 });
    await page.reload();
    await expect(page.getByText("Factor 2").first()).toBeVisible();
    await shot(page, "08b_replication_factor_2");

    await page.getByRole("button", { name: "Increase replication factor" }).click();
    await page.getByRole("button", { name: "Apply factor 3" }).click();
    await expect(page.getByRole("cell", { name: "2 to 3" })).toBeVisible({ timeout: 30_000 });
    await waitUntil(
      async () => {
        const data = await (await fetch(`${API}/cluster/replication`)).json();
        return data.operations[0].status === "verified";
      },
      700,
      "replication 3",
    );
    // NameNode JMX values are cached for about ten seconds, so wait for the health summary to catch up.
    await waitUntil(async () => (await (await fetch(`${API}/cluster/status`)).json()).health === "healthy", 60, "healthy status");
    await page.reload();
    await expect(page.getByText("Factor 3").first()).toBeVisible();
    await shot(page, "08_replication_management");
  });

  test("experiments run from the lab", async ({ page }) => {
    await page.goto("/lab");
    for (const title of ["Fixed-size chunking boundary shift", "Logical deletion with shared content"]) {
      const row = page.locator("li").filter({ hasText: title });
      await row.getByRole("button", { name: "Run" }).click();
      await expect(row.getByText("succeeded")).toBeVisible({ timeout: 120_000 });
      await page.waitForTimeout(800);
    }
    await expect(page.locator("[data-sonner-toast]")).toHaveCount(0, { timeout: 15_000 });
    await shot(page, "17a_experiment_lab");
  });

  test("final state pages", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Storage reduction")).toBeVisible();
    await page.waitForTimeout(800);
    await shot(page, "01_dashboard");
    await page.goto("/analytics");
    await page.waitForTimeout(800);
    await shot(page, "07_storage_analytics");
    await page.goto("/cluster");
    await expect(page.getByRole("cell", { name: "datanode1" })).toBeVisible();
    await shot(page, "09_cluster_status");
    await page.goto("/activity");
    await expect(page.getByRole("cell", { name: "optimize.completed" }).first()).toBeVisible();
    await shot(page, "09a_activity_audit", false);
    await page.goto("/settings");
    await page.getByRole("button", { name: "Run diagnostics" }).click();
    await expect(page.getByText(/Wrote, read back and deleted/)).toBeVisible();
    await page.getByRole("button", { name: "Check" }).click();
    await expect(page.getByText(/files in HDFS,/)).toBeVisible();
    await shot(page, "09b_settings_diagnostics");
  });

  test("dark mode and phone width", async ({ browser }) => {
    const dark = await browser.newContext({ baseURL: "http://localhost:3100", viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "dark" });
    const darkPage = await dark.newPage();
    await darkPage.goto("/");
    await expect(darkPage.getByText("Storage reduction")).toBeVisible();
    await darkPage.waitForTimeout(800);
    await shot(darkPage, "01a_dashboard_dark");
    await darkPage.goto("/duplicates");
    await darkPage.waitForTimeout(500);
    await shot(darkPage, "04a_duplicates_dark", false);
    await dark.close();
    const phone = await browser.newContext({ baseURL: "http://localhost:3100", viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: "light" });
    const phonePage = await phone.newPage();
    await phonePage.goto("/");
    await expect(phonePage.getByText("Storage reduction")).toBeVisible();
    await phonePage.waitForTimeout(800);
    await shot(phonePage, "01b_dashboard_phone", false);
    await phone.close();
  });

  test("NameNode, DataNode and API documentation pages", async ({ page }) => {
    await page.goto("http://127.0.0.1:9870/dfshealth.html#tab-overview");
    await expect(page.getByText("Overview")).toBeVisible();
    await page.waitForTimeout(1500);
    await shot(page, "10_namenode_interface");
    await page.goto("http://127.0.0.1:9870/dfshealth.html#tab-datanode");
    await page.waitForTimeout(1500);
    await shot(page, "11_datanode_status");
    await page.goto("http://127.0.0.1:19864/datanode.html");
    await page.waitForTimeout(1500);
    await shot(page, "11a_datanode_interface", false);
    await page.goto("http://localhost:8100/docs");
    await page.waitForTimeout(2500);
    await shot(page, "12b_api_documentation", false);
  });

  test("a real DataNode outage is shown as it happens", async ({ page }) => {
    test.setTimeout(420_000);
    compose("stop", "datanode3");
    try {
      await waitUntil(async () => (await jmx())?.NumDeadDataNodes === 1, 240, "the DataNode to be declared dead");
      // The NameNode removes a dead node's replicas on its own cycle, slightly after flagging it as dead.
      await waitUntil(async () => (await (await fetch(`${API}/cluster/replication`)).json()).fsck.under_replicated_blocks > 0, 120, "fsck to report under-replication");
      await waitUntil(async () => ((await jmx())?.UnderReplicatedBlocks ?? 0) > 0, 60, "cached JMX values to catch up");
      await page.goto("/cluster");
      await expect(page.getByText("Degraded").first()).toBeVisible({ timeout: 30_000 });
      await shot(page, "09c_cluster_datanode_dead");
      await page.goto("/replication");
      await expect(page.getByText(/under-replicated/).first()).toBeVisible();
      await shot(page, "09d_replication_datanode_dead");
    } finally {
      compose("start", "datanode3");
    }
    await waitUntil(async () => {
      const bean = await jmx();
      if (bean?.NumLiveDataNodes !== 3) return false;
      return (await (await fetch(`${API}/cluster/replication`)).json()).fsck.under_replicated_blocks === 0;
    }, 240, "the DataNode to recover");
  });

  test("a real NameNode outage is shown as it happens", async ({ page }) => {
    test.setTimeout(420_000);
    compose("stop", "namenode");
    try {
      await waitUntil(async () => (await jmx()) === null, 60, "the NameNode to stop");
      await page.goto("/cluster");
      await expect(page.getByText("The NameNode is not responding")).toBeVisible({ timeout: 30_000 });
      await shot(page, "09e_cluster_namenode_down", false);
      await page.goto("/files");
      await page.getByTestId("file-input").setInputFiles({ name: "during-outage.txt", mimeType: "text/plain", buffer: readFileSync(path.join(DATASET, "originals/pg11.txt")) });
      await expect(page.getByText(/Cannot reach the NameNode/)).toBeVisible({ timeout: 30_000 });
      await shot(page, "09f_upload_during_outage", false);
    } finally {
      compose("start", "namenode");
    }
    await waitUntil(async () => (await jmx())?.NumLiveDataNodes === 3, 240, "the cluster to recover");
    await waitUntil(async () => (await (await fetch(`${API}/system/diagnostics`)).json()).ok === true, 120, "writes to resume");
  });

  test("terminal evidence is rendered from captured output", async ({ page }) => {
    // Output files are written by scripts/capture_terminal.sh. They are displayed unedited.
    for (const file of readdirSync(EVIDENCE).filter((f) => f.endsWith(".txt")).sort()) {
      const text = readFileSync(path.join(EVIDENCE, file), "utf8");
      const lines = text.split("\n");
      const shown = lines.length > 70 ? [...lines.slice(0, 66), `... (${lines.length - 66} more lines in evidence/${file})`] : lines;
      const escaped = shown.join("\n").replace(/&/g, "&amp;").replace(/</g, "&lt;");
      const html = `<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#141413;color:#e8e7e3;font:13px/1.45 Menlo,Consolas,monospace;padding:18px 22px}pre{margin:0;white-space:pre-wrap;word-break:break-word}</style><pre>${escaped}</pre>`;
      const temp = path.join(EVIDENCE, ".render.html");
      writeFileSync(temp, html);
      await page.setViewportSize({ width: 1180, height: 200 });
      await page.goto(`file://${temp}`);
      await page.screenshot({ path: path.join(SHOTS, `terminal_${file.replace(".txt", "")}.png`), fullPage: true });
    }
  });
});
