const UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes === null || bytes === undefined) return "N/A";
  const sign = bytes < 0 ? "-" : "";
  let value = Math.abs(bytes);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const shown = unit === 0 ? value.toFixed(0) : value.toFixed(value >= 100 ? 0 : digits);
  return `${sign}${shown} ${UNITS[unit]}`;
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "N/A" : value.toLocaleString("en-US");
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "N/A" : `${value.toFixed(digits)}%`;
}

export function formatRatio(value: number | null | undefined): string {
  return value === null || value === undefined ? "N/A" : `${value.toFixed(2)} : 1`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "N/A";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

/** The backend stores naive UTC timestamps. */
export function parseTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "N/A";
  return parseTime(value).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatTime(value: string): string {
  return parseTime(value).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function shortHash(hash: string | null | undefined, length = 12): string {
  return hash ? hash.slice(0, length) : "N/A";
}

export const MODE_LABEL: Record<string, string> = {
  raw: "No dedup",
  file: "Whole file",
  chunk: "Chunked",
};

export const PROVENANCE_LABEL: Record<string, string> = {
  user_upload: "Uploaded",
  dataset_original: "Dataset original",
  workload_copy: "Workload copy",
  transformed: "Transformed test file",
};

export const CHUNK_SIZES = [
  { value: 64 * 1024, label: "64 KiB" },
  { value: 256 * 1024, label: "256 KiB" },
  { value: 1024 * 1024, label: "1 MiB" },
  { value: 4 * 1024 * 1024, label: "4 MiB" },
];

export function chunkSizeLabel(bytes: number | null | undefined): string {
  return bytes ? formatBytes(bytes, 0) : "N/A";
}
