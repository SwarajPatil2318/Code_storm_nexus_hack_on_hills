import type { Metadata } from "next";
import { GuidedBlue } from "@/components/guided/blue-workspace";
export const metadata: Metadata = { title: "Defence Vault" };
export default function Page() {
  return <GuidedBlue />;
}
