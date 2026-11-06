import type { UploadResult } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

function describeValidation(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return String(detail);
}

async function toError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  if (body?.error) return new ApiError(body.error.message, response.status, body.error.code, body.error.details);
  if (body?.detail) return new ApiError(describeValidation(body.detail), response.status, "validation_failed");
  return new ApiError(`The server returned ${response.status}.`, response.status, "http_error");
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(API_TOKEN ? { "X-API-Key": API_TOKEN } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(`Cannot reach the backend at ${API_URL}. Is it running?`, 0, "backend_unreachable");
  }
  if (!response.ok) throw await toError(response);
  return (await response.json()) as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

export interface UploadOptions {
  folder: string;
  mode: string;
  chunkSize?: number;
  onProgress: (sentFraction: number) => void;
}

/** XMLHttpRequest is used because fetch cannot report upload progress. The fraction is what the browser really sent. */
export function uploadFile(file: File, options: UploadOptions): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("folder", options.folder);
    form.append("mode", options.mode);
    if (options.chunkSize) form.append("chunk_size", String(options.chunkSize));

    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}/api/v1/files/upload`);
    if (API_TOKEN) request.setRequestHeader("X-API-Key", API_TOKEN);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      let body: { error?: { message: string; code: string }; detail?: unknown } | UploadResult | null = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        /* handled below */
      }
      if (request.status >= 200 && request.status < 300 && body) {
        resolve(body as UploadResult);
        return;
      }
      const failure = body as { error?: { message: string; code: string }; detail?: unknown } | null;
      reject(
        new ApiError(
          failure?.error?.message ?? (failure?.detail ? describeValidation(failure.detail) : `Upload failed (${request.status}).`),
          request.status,
          failure?.error?.code ?? "upload_failed",
        ),
      );
    };
    request.onerror = () => reject(new ApiError(`Cannot reach the backend at ${API_URL}.`, 0, "backend_unreachable"));
    request.send(form);
  });
}
