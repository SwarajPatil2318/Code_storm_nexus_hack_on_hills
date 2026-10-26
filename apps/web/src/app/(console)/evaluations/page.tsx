import type { Metadata } from "next";
import { EvaluationList } from "@/components/guided/evaluation-list";
export const metadata: Metadata = { title: "Evaluations" };
export default function Page() {
  return <EvaluationList />;
}
