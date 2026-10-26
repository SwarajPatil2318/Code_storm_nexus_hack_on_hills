import type { Metadata } from "next";
import { AssuranceWorkspace } from "@/components/assurance-workspace";
export const metadata: Metadata = { title: "Resource Assurance" };
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ evaluation?: string; archive?: string }>;
}) {
  await searchParams;
  return <AssuranceWorkspace kind="resource" />;
}
