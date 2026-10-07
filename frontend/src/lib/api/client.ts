import { clearToken, getToken } from "@/lib/auth/token";
import type { ApiErrorBody } from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path.replace(/^\//, ""), `${API_BASE_URL}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parseErrorBody(res: Response): Promise<ApiErrorBody["detail"]["error"]> {
  try {
    const body = (await res.json()) as Partial<ApiErrorBody>;
    const error = body?.detail?.error;
    if (error?.code && error?.message) return error;
  } catch {
    // response had no JSON body
  }
  return { code: "unknown_error", message: res.statusText || `Request failed (${res.status})` };
}

/** The shared request path for every JSON endpoint. Attaches the bearer
 * token when present; a 401 clears it (the session is dead either way). */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    cache: "no-store",
  });

  if (res.status === 401) {
    clearToken();
  }

  if (!res.ok) {
    const error = await parseErrorBody(res);
    throw new ApiError(res.status, error.code, error.message, error.details);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** multipart/form-data upload -- never JSON-stringified, never given a
 * Content-Type header (the browser sets the multipart boundary itself). */
export async function apiUpload<T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(buildUrl(path), { method: "POST", headers, body: form, signal });
  if (res.status === 401) clearToken();
  if (!res.ok) {
    const error = await parseErrorBody(res);
    throw new ApiError(res.status, error.code, error.message, error.details);
  }
  return (await res.json()) as T;
}

/** A file the API sends (an export): its bytes, and the name the server gave it. */
export async function apiDownload(
  path: string,
  query?: RequestOptions["query"],
): Promise<{ blob: Blob; filename: string | null }> {
  const res = await fetch(buildUrl(path, query), { headers: authHeader(), cache: "no-store" });
  if (res.status === 401) clearToken();
  if (!res.ok) {
    const error = await parseErrorBody(res);
    throw new ApiError(res.status, error.code, error.message, error.details);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? null;
  return { blob: await res.blob(), filename };
}

export function authHeader(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
