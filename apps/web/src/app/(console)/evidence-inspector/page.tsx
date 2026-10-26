import type { Metadata } from "next";
import { WorkspacePage } from "@/components/workspace-pages";
export const metadata: Metadata = { title: "Evidence Inspector" };
export default function Page() {
  return <WorkspacePage kind="evidence-inspector" />;
}
