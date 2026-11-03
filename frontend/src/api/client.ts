// HTTP client for the backend-for-frontend API. The browser never holds tokens: requests carry
// the HttpOnly session cookie, and state-changing requests echo the CSRF cookie in a header.

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  correlation_id: string | null;
  errors?: Record<string, string[]>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail);
    this.status = problem.status;
    this.problem = problem;
  }

  get code(): string {
    return this.problem.code;
  }

  fieldErrors(): Record<string, string[]> {
    return this.problem.errors ?? {};
  }
}

const CSRF_COOKIE = "__Host-fcp_csrftoken";

function csrfToken(): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : "";
}

async function toProblem(response: Response): Promise<Problem> {
  try {
    return (await response.json()) as Problem;
  } catch {
    return {
      type: "about:blank",
      title: response.statusText || "Request failed",
      status: response.status,
      detail: "The server returned an unexpected response. Please try again.",
      code: "http_error",
      correlation_id: null,
    };
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  idempotencyKey?: string;
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`/api${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.pathname + url.search;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["X-CSRFToken"] = csrfToken();
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  const init: RequestInit = { method, headers, credentials: "same-origin" };
  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(apiUrl(path, options.query), init);
  if (!response.ok) {
    throw new ApiError(await toProblem(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function loginUrl(next: string = window.location.pathname): string {
  return `/auth/login?next=${encodeURIComponent(next)}`;
}

export function newIdempotencyKey(): string {
  return `ui-${crypto.randomUUID()}`;
}
