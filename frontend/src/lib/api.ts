import { useAuthStore } from "@/stores/auth-store";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

type QueryValue = string | number | boolean | null | undefined;

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, QueryValue | QueryValue[]>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Skip attaching the Authorization header (e.g. for /auth/login). */
  skipAuth?: boolean;
}

function buildUrl(path: string, query?: ApiFetchOptions["query"]): string {
  const base = path.startsWith("http") ? path : `${API_BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [key, raw] of Object.entries(query)) {
    if (raw == null) continue;
    if (Array.isArray(raw)) {
      for (const v of raw) {
        if (v == null) continue;
        params.append(key, String(v));
      }
    } else {
      params.append(key, String(raw));
    }
  }
  const qs = params.toString();
  if (!qs) return base;
  return `${base}${base.includes("?") ? "&" : "?"}${qs}`;
}

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  const fromStore = useAuthStore.getState().token;
  if (fromStore) return fromStore;
  try {
    const raw = window.localStorage.getItem("apex-auth");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { token?: string | null } };
    return parsed.state?.token ?? null;
  } catch {
    return null;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const { method = "GET", body, query, headers = {}, signal, skipAuth = false } = options;

  const finalHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  if (body !== undefined && !(body instanceof FormData) && !finalHeaders["Content-Type"]) {
    finalHeaders["Content-Type"] = "application/json";
  }
  if (!skipAuth) {
    const token = readToken();
    if (token && !finalHeaders["Authorization"]) {
      finalHeaders["Authorization"] = `Bearer ${token}`;
    }
  }

  let payload: BodyInit | undefined;
  if (body !== undefined) {
    if (body instanceof FormData || typeof body === "string") {
      payload = body as BodyInit;
    } else {
      payload = JSON.stringify(body);
    }
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      headers: finalHeaders,
      body: payload,
      signal,
      credentials: "omit",
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network request failed";
    throw new ApiError(message, 0);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const parsed: unknown = isJson ? await res.json().catch(() => null) : await res.text().catch(() => "");

  if (!res.ok) {
    const detail =
      isJson && parsed && typeof parsed === "object"
        ? (parsed as { detail?: unknown; message?: unknown }).detail ??
          (parsed as { message?: unknown }).message
        : typeof parsed === "string" && parsed
          ? parsed
          : undefined;
    const message =
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status, parsed);
  }

  return parsed as T;
}
