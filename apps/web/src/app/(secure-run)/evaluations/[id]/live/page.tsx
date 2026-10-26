import type { Metadata } from "next";
import { SecureEvaluation } from "@/components/guided/secure-evaluation";
export const metadata: Metadata = { title: "Live Secure Evaluation" };
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SecureEvaluation id={id} />;
}
