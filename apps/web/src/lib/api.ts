import type { components } from "./api.generated";
export type Health = components["schemas"]["HealthResponse"];
export type Readiness = components["schemas"]["ReadyResponse"];
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number | null,
  ) {
    super(message);
  }
}
export const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
function endpoint(path: string) {
  let url: URL;
  try {
    url = new URL(apiUrl);
  } catch {
    throw new ApiError("API URL is invalid. Check NEXT_PUBLIC_API_URL.", null);
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new ApiError("API URL must be an HTTP(S) origin without credentials or a path.", null);
  }
  return new URL(path, url).toString();
}
async function request(
  path: string,
  signal: AbortSignal,
  allowUnavailable = false,
): Promise<{ body: unknown; status: number }> {
  const response = await fetch(endpoint(path), {
    signal,
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok && !(allowUnavailable && response.status === 503)) {
    throw new ApiError(`API returned HTTP ${response.status}.`, response.status);
  }
  try {
    return { body: await response.json(), status: response.status };
  } catch {
    throw new ApiError("API returned an invalid JSON response.", response.status);
  }
}
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
export async function getHealth(signal: AbortSignal): Promise<Health> {
  const { body } = await request("/health", signal);
  if (
    !isObject(body) ||
    body.status !== "ok" ||
    body.service !== "nexus-api" ||
    body.mode !== "foundation" ||
    typeof body.version !== "string"
  ) {
    throw new ApiError("Unexpected health response. Verify the API address and version.", 200);
  }
  return body as Health;
}
export async function getReadiness(signal: AbortSignal): Promise<Readiness> {
  const { body, status } = await request("/ready", signal, true);
  if (
    !isObject(body) ||
    !["ready", "not_ready"].includes(String(body.status)) ||
    !["connected", "unconfigured", "unavailable", "migration_required"].includes(
      String(body.database),
    ) ||
    (body.status === "ready") !== (body.database === "connected") ||
    (body.status === "ready") !== (status === 200)
  ) {
    throw new ApiError("Unexpected readiness response.", 200);
  }
  return body as Readiness;
}
