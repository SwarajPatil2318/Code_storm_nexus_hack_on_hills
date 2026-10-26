import type { Metadata } from "next";
import { EvaluationDetail } from "@/components/guided/evaluation-detail";
export const metadata: Metadata = { title: "Evaluation" };
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvaluationDetail id={id} />;
}
