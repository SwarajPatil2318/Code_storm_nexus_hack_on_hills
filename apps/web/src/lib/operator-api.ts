import type { components } from "./api.generated";
export class WorkspaceApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public caseErrors: { line: number; code: string }[] = [],
  ) {
    super(message);
  }
}
export type Artifact = components["schemas"]["ArtifactResponse"];
export type Evaluation = components["schemas"]["EvaluationResponse"];
export type User = components["schemas"]["UserResponse"];
export type EventRecord = components["schemas"]["SecurityEventResponse"];
export async function operatorRequest<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PATCH" | "DELETE";
    body?: unknown;
    csrf?: string;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.csrf) headers["X-CSRF-Token"] = options.csrf;
  const response = await fetch(`/api${path}`, {
    method: options.method || "GET",
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal || AbortSignal.timeout(12000),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && path !== "/auth/csrf")
      window.dispatchEvent(new Event("nexus:unauthorized"));
    throw new WorkspaceApiError(
      data.error?.message || `Request failed (${response.status})`,
      response.status,
      data.error?.code || "request_failed",
      Array.isArray(data.case_errors)
        ? data.case_errors.filter(
            (item: { line?: unknown; code?: unknown }) =>
              Number.isSafeInteger(item.line) &&
              typeof item.code === "string" &&
              ["INVALID_CASE_SCHEMA", "TOO_MANY_CASES"].includes(item.code),
          )
        : [],
    );
  }
  return data as T;
}

/** A full navigation discards the former operator's in-memory data and Next router cache. */
export function resetIdentityNavigation(path: "/" | "/login") {
  window.location.assign(path);
}
