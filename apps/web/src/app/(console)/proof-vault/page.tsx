import { ArchiveEvidence } from "@/components/archive-evidence";
import type { Metadata } from "next";
import { ProofVault } from "@/components/proof-vault";
export const metadata: Metadata = { title: "Proof Vault" };
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ evaluation?: string; sequence?: string; archive?: string }>;
}) {
  const params = await searchParams;
  if (typeof params.archive === "string")
    return (
      <ArchiveEvidence
        id={params.archive}
        mode="proof"
        sequence={typeof params.sequence === "string" ? params.sequence : ""}
      />
    );
  return (
    <ProofVault
      initialEvaluation={typeof params.evaluation === "string" ? params.evaluation : ""}
      initialSequence={typeof params.sequence === "string" ? params.sequence : ""}
    />
  );
}
