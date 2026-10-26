import { ArchiveEvidence } from "@/components/archive-evidence";
import { XrayWorkspace } from "@/components/xray/workspace";
export const metadata = { title: "NEXUS X-Ray | Execution & Forensics" };
export default async function XrayPage({
  searchParams,
}: {
  searchParams: Promise<{ archive?: string }>;
}) {
  const params = await searchParams;
  if (typeof params.archive === "string")
    return <ArchiveEvidence id={params.archive} mode="trace" />;
  return <XrayWorkspace />;
}
