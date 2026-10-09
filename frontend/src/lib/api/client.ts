import { csrfHeader, notifyUnauthorized } from "@/lib/auth/session";
import type { ApiErrorBody } from "./types";

/**
 * Where the API is. Unset: the local backend (http://localhost:8000). An
 * empty value: this same site -- a deployment serves the API under /api on
 * the app's own address, so a production build carries no backend URL.
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

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

export function apiBase(): string {
  if (API_BASE_URL) return API_BASE_URL;
  return typeof window === "undefined" ? "http://localhost" : window.location.origin;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path.replace(/^\//, ""), `${apiBase()}/`);
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

/** A 401 from anything but the "who am I" check means the session ended
 * (expired, or signed out elsewhere): have the app check again. */
function sawUnauthorized(path: string, status: number): void {
  if (status === 401 && path !== "/api/v1/auth/session") notifyUnauthorized();
}

/** The shared request path for every JSON endpoint. The session travels as
 * a cookie; a state-changing request also carries the CSRF header. */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...csrfHeader(method) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(buildUrl(path, options.query), {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    cache: "no-store",
    credentials: "include",
  });

  sawUnauthorized(path, res.status);

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
  const headers: Record<string, string> = { Accept: "application/json", ...csrfHeader("POST") };
  const res = await fetch(buildUrl(path), { method: "POST", headers, body: form, signal, credentials: "include" });
  sawUnauthorized(path, res.status);
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
  const res = await fetch(buildUrl(path, query), { cache: "no-store", credentials: "include" });
  sawUnauthorized(path, res.status);
  if (!res.ok) {
    const error = await parseErrorBody(res);
    throw new ApiError(res.status, error.code, error.message, error.details);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? null;
  return { blob: await res.blob(), filename };
}
