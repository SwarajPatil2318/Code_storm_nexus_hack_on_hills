import type { components } from "./api.generated";
export type Role = components["schemas"]["Role"];
export type OperatorSession = components["schemas"]["SessionResponse"];
export type Operator = components["schemas"]["UserResponse"];
export type SecurityEvent = components["schemas"]["SecurityEventResponse"];
export const roleLabels: Record<Role, string> = {
  RED_OPERATOR: "Red operator",
  BLUE_OPERATOR: "Blue operator",
  AUDITOR: "Auditor",
  ADMIN: "Administrator",
};
export function parseSession(value: unknown): OperatorSession {
  const body = value as Partial<OperatorSession> | null;
  if (
    !body ||
    !body.user ||
    !Object.hasOwn(roleLabels, body.user.role) ||
    typeof body.user.id !== "string" ||
    typeof body.user.display_name !== "string" ||
    typeof body.csrf_token !== "string" ||
    typeof body.expires_at !== "string" ||
    !Number.isFinite(Date.parse(body.expires_at))
  ) {
    throw new Error("The identity service returned an invalid session.");
  }
  return body as OperatorSession;
}
export function permittedRoute(role: Role, href: string): boolean {
  if (href === "/evaluations" || href.startsWith("/evaluations/")) return role !== "ADMIN";
  if (href === "/llm-assurance" || href === "/resource-assurance")
    return role === "RED_OPERATOR" || role === "AUDITOR";
  if (href === "/attack-lab") return role === "RED_OPERATOR";
  if (href === "/defence-vault") return role === "BLUE_OPERATOR";
  if (href === "/assurance-center" || href === "/security-overview") return role !== "ADMIN";
  if (href === "/proof-vault") return role !== "ADMIN";
  if (href === "/evidence-inspector") return role === "AUDITOR";
  if (href === "/users") return role === "ADMIN";
  return true;
}
