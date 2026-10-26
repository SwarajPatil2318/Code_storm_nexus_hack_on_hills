import { cookies } from "next/headers";
import { parseSession, type OperatorSession } from "./auth-types";
export function internalApiOrigin(): string {
  const url = new URL(process.env.NEXUS_API_INTERNAL_URL || "http://127.0.0.1:8000");
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error("Invalid internal API origin");
  return url.origin;
}
export async function serverSession(): Promise<OperatorSession | null> {
  const jar = await cookies();
  const session = jar.get("__Host-nexus_session") || jar.get("nexus_session");
  if (!session) return null;
  const response = await fetch(`${internalApiOrigin()}/auth/session`, {
    cache: "no-store",
    headers: { Cookie: `${session.name}=${session.value}` },
    signal: AbortSignal.timeout(6000),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Identity service unavailable");
  return parseSession(await response.json());
}
