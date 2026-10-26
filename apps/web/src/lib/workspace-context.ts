// Carry only validated identities into workspaces that support that evidence type.
export function workspaceHref(href: string, pathname: string, search: string): string {
  const params = new URLSearchParams(search);
  const valid = (id: string | null) =>
    id && /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(id) ? id : null;
  const archive = valid(params.get("archive"));
  if (archive) {
    if (["/x-ray", "/proof-vault"].includes(href) || href === pathname)
      return `${href}?archive=${archive}`;
    if (["/llm-assurance", "/resource-assurance"].includes(href))
      return `${href}?context=experiments`;
    return href;
  }
  const evaluation = valid(
    pathname.match(/^\/evaluations\/([^/]+)(?:\/live)?$/)?.[1] || params.get("evaluation"),
  );
  return evaluation &&
    [
      "/x-ray",
      "/proof-vault",
      "/isolation-observatory",
      "/llm-assurance",
      "/resource-assurance",
      "/assurance-center",
    ].includes(href)
    ? `${href}?evaluation=${evaluation}`
    : href;
}
