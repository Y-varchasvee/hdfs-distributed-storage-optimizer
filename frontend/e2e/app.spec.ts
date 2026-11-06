import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const DATASET = path.resolve(__dirname, "../../datasets/raw/originals");
const ALICE = path.join(DATASET, "pg11.txt");
const aliceHash = createHash("sha256").update(readFileSync(ALICE)).digest("hex");

const PAGES = [
  ["/", "Dashboard"],
  ["/files", "Files"],
  ["/duplicates", "Duplicates"],
  ["/optimize", "Optimization center"],
  ["/replication", "Replication manager"],
  ["/cluster", "Cluster monitoring"],
  ["/analytics", "Analytics and reports"],
  ["/activity", "Activity and audit"],
  ["/lab", "Dataset and experiment lab"],
  ["/settings", "Settings"],
] as const;

test.beforeEach(async ({ context }) => {
  // The production build talks to port 8100. Send those calls to the isolated test backend.
  await context.route("http://localhost:8100/**", (route) => route.continue({ url: route.request().url().replace("localhost:8100", "127.0.0.1:8199") }));
});

function failOnConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function upload(page: Page, mode: "Whole-file dedup" | "Chunk-level dedup" | "No dedup (baseline)", files: { name: string; path: string }[]) {
  await page.goto("/files");
  await page.getByRole("combobox", { name: "Storage mode for new uploads" }).click();
  await page.getByRole("option", { name: mode }).click();
  await page.getByTestId("file-input").setInputFiles(files.map((f) => ({ name: f.name, mimeType: "text/plain", buffer: readFileSync(f.path) })));
}

test.describe.serial("HDFS Optimizer", () => {
  test("every page renders without console errors", async ({ page }) => {
    const errors = failOnConsoleErrors(page);
    for (const [url, heading] of PAGES) {
      await page.goto(url);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await page.waitForLoadState("networkidle");
    }
    expect(errors).toEqual([]);
  });

  test("an empty system shows N/A, not invented values", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("No files are managed yet")).toBeVisible();
    await expect(page.getByText("N/A").first()).toBeVisible();
  });

  test("the cluster page shows real DataNodes", async ({ page }) => {
    await page.goto("/cluster");
    await expect(page.getByRole("cell", { name: "datanode1" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "datanode3" })).toBeVisible();
    await expect(page.getByText("3.5.0").first()).toBeVisible();
  });

  test("uploading the same authentic file twice stores it once", async ({ page }) => {
    await upload(page, "Whole-file dedup", [{ name: "alice.txt", path: ALICE }]);
    await expect(page.getByText("New content stored")).toBeVisible();
    await page.getByTestId("file-input").setInputFiles({ name: "same-book-other-name.txt", mimeType: "text/plain", buffer: readFileSync(ALICE) });
    await expect(page.getByText("Duplicate: no new data stored")).toBeVisible();
    await expect(page.getByRole("cell", { name: /same-book-other-name\.txt/ })).toBeVisible();
    await expect(page.getByText("2 references").first()).toBeVisible();
  });

  test("download restores identical bytes, and verification passes", async ({ page }) => {
    await page.goto("/files");
    await page.getByRole("button", { name: "same-book-other-name.txt" }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: "Download" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("same-book-other-name.txt");
    const restored = readFileSync(await download.path());
    expect(createHash("sha256").update(restored).digest("hex")).toBe(aliceHash);

    await page.getByRole("button", { name: "Verify integrity" }).click();
    await expect(page.getByText("SHA-256 matches")).toBeVisible();
  });

  test("the duplicates page explains the relationship", async ({ page }) => {
    await page.goto("/duplicates");
    await expect(page.getByRole("img", { name: /2 logical files share SHA-256/ })).toBeVisible();
    await expect(page.getByText("Deduplicated").first()).toBeVisible();
  });

  test("delete keeps shared content and restore brings the file back", async ({ page }) => {
    await page.goto("/files");
    await page.getByRole("button", { name: "alice.txt" }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByRole("button", { name: "alice.txt" })).toBeHidden();

    await page.getByRole("combobox", { name: "Active or deleted files" }).click();
    await page.getByRole("option", { name: "Recently deleted" }).click();
    await page.getByRole("button", { name: "alice.txt" }).click();
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByText("File restored.")).toBeVisible();
  });

  test("optimization needs a preview, then reclaims space and keeps bytes intact", async ({ page }) => {
    const sherlock = path.join(DATASET, "pg1661.txt");
    await upload(page, "No dedup (baseline)", [
      { name: "sherlock-a.txt", path: sherlock },
      { name: "sherlock-b.txt", path: sherlock },
      { name: "sherlock-c.txt", path: sherlock },
    ]);
    await expect(page.getByText("Stored without deduplication")).toHaveCount(3, { timeout: 30_000 });

    await page.goto("/optimize");
    await expect(page.getByRole("button", { name: "Start optimization" })).toBeHidden();
    await page.getByRole("button", { name: "Run dry-run analysis" }).click();
    await expect(page.getByText("Nothing has changed yet.")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Expected reduction")).toBeVisible();

    await page.getByRole("button", { name: "Start optimization" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Start optimization" }).click();
    await expect(page.getByText("Results below are observed, not predicted.")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Stored content reclaimed")).toBeVisible();

    await page.getByRole("button", { name: "Verify all restored bytes" }).click();
    await expect(page.getByText(/5 of 5 files match their SHA-256/)).toBeVisible({ timeout: 60_000 });
  });

  test("chunk mode shows shared chunks in the chunk map", async ({ page }) => {
    const workload = path.resolve(__dirname, "../../datasets/raw/workload");
    await upload(page, "Chunk-level dedup", [
      { name: "pride.txt", path: path.join(DATASET, "pg1342.txt") },
      { name: "pride-truncated.txt", path: path.join(workload, "pg1342.truncate_90.txt") },
    ]);
    await expect(page.getByText(/chunks reused/)).toHaveCount(2, { timeout: 30_000 });
    await page.goto("/duplicates");
    await page.getByRole("tab", { name: "Shared chunks" }).click();
    await expect(page.getByText("pride-truncated.txt")).toBeVisible();
    await expect(page.getByRole("img", { name: /chunks shown are shared/ }).first()).toBeVisible();
  });

  test("replication above live DataNodes is not offered, and lowering asks for confirmation", async ({ page }) => {
    await page.goto("/replication");
    await expect(page.getByRole("button", { name: "Increase replication factor" })).toBeDisabled();
    await page.getByRole("button", { name: "Decrease replication factor" }).click();
    await page.getByRole("button", { name: "Apply factor 2" }).click();
    await expect(page.getByRole("dialog")).toContainText("reduces fault tolerance");
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  });

  test("the audit trail records what happened", async ({ page }) => {
    await page.goto("/activity");
    await expect(page.getByRole("cell", { name: "file.uploaded" }).first()).toBeVisible();
    await expect(page.getByRole("cell", { name: "dedup.duplicate_detected" }).first()).toBeVisible();
    await expect(page.getByRole("cell", { name: "optimize.completed" }).first()).toBeVisible();
  });

  test("diagnostics run real checks against the cluster", async ({ page }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: "Run diagnostics" }).click();
    await expect(page.getByText(/Wrote, read back and deleted/)).toBeVisible();
    await expect(page.getByText(/SQLite integrity_check returned ok/)).toBeVisible();
  });

  test("mobile layout has no horizontal page scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const [url] of PAGES) {
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${url} overflows horizontally`).toBeLessThanOrEqual(0);
    }
  });
});
