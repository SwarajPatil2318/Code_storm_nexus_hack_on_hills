import type { NextRequest } from "next/server";
import { internalApiOrigin } from "@/lib/server-api";
const uuid = "[0-9a-fA-F-]{36}";
const allowed = new RegExp(
  `^/(assurance-center(/evaluations(/${uuid})?|/archives/${uuid}(/(bundle|history))?|/experiments/${uuid})?|(assurance|resource-assurance)/evaluations(/${uuid})?|proof/evaluations(/${uuid}(/(finalize|verify)|/receipts/${uuid}/(bundle|verify|events/[0-9]{1,4}))?)?|auth/(csrf|login|logout|session|demo)|artifacts(/${uuid}(/(content|versions))?)?|evaluations(/${uuid}(/(events|history|result|manifest|commit|approve|seal|start|cancel|destroy|released-result|auditor|runtime|probes))?)?|campaigns(/(providers|versions|starter-corpus|corpora/import|corpora/${uuid}/export|${uuid}))?|comparisons(/${uuid})?|versions(/${uuid}/grants)?|policies/${uuid}|runtime/capabilities|audit-events|admin/users(/${uuid})?)$`,
);
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = "/" + (await context.params).path.join("/");
  const params = request.nextUrl.searchParams;
  const archiveHistory = new RegExp(`^/assurance-center/archives/${uuid}/history$`).test(path);
  const history = archiveHistory || new RegExp(`^/evaluations/${uuid}/history$`).test(path);
  const safeQuery =
    history &&
    request.method === "GET" &&
    [...params.keys()].every(
      (key) =>
        (archiveHistory ? ["after", "limit"] : ["after", "limit", "until"]).includes(key) &&
        params.getAll(key).length === 1 &&
        /^[0-9]{1,13}$/.test(params.get(key) || ""),
    );
  if (!allowed.test(path) || (request.nextUrl.search && !safeQuery))
    return Response.json(
      { error: { code: "not_found", message: "Unknown API route" } },
      { status: 404 },
    );
  const headers = new Headers({ Accept: "application/json" });
  for (const key of ["Content-Type", "Origin", "X-CSRF-Token"]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  const cookie =
    request.cookies.get("__Host-nexus_session") || request.cookies.get("nexus_session");
  if (cookie) headers.set("Cookie", `${cookie.name}=${cookie.value}`);
  try {
    let body: string | undefined;
    if (!["GET", "HEAD"].includes(request.method) && request.body) {
      const limit = new RegExp(`^/proof/evaluations/${uuid}/verify$`).test(path) ? 8388608 : 131072;
      const reader = request.body.getReader();
      let size = 0,
        expired = false;
      const parts: Uint8Array[] = [];
      const timer = setTimeout(() => {
        expired = true;
        void reader.cancel();
      }, 10000);
      try {
        for (;;) {
          const value = await reader.read();
          if (value.done) break;
          size += value.value.byteLength;
          if (size > limit) {
            await reader.cancel();
            return Response.json(
              { error: { code: "body_too_large", message: "Request body is too large" } },
              { status: 413 },
            );
          }
          parts.push(value.value);
        }
        if (expired)
          return Response.json(
            { error: { code: "upload_timeout", message: "Upload deadline exceeded" } },
            { status: 408 },
          );
        const bytes = new Uint8Array(size);
        let offset = 0;
        for (const part of parts) {
          bytes.set(part, offset);
          offset += part.byteLength;
        }
        body = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } finally {
        clearTimeout(timer);
        reader.releaseLock();
      }
    }
    const upstream = await fetch(
      `${internalApiOrigin()}${path}${history ? request.nextUrl.search : ""}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      },
    );
    const outgoing = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "content-disposition", "x-request-id"]) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    for (const value of upstream.headers.getSetCookie()) outgoing.append("Set-Cookie", value);
    return new Response(upstream.status === 204 ? null : await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: outgoing,
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "api_unavailable",
          message: "The API is unavailable. Start the backend and try again.",
        },
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
