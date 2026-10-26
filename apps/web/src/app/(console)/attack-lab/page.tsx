import type { Metadata } from "next";
import { GuidedRed } from "@/components/guided/red-workflow";
export const metadata: Metadata = { title: "Attack Lab" };
export default function Page() {
  return <GuidedRed />;
}
