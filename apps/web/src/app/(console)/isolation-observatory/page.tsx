import type { Metadata } from "next";
import { ObservatoryPage } from "@/components/workspace-pages";
export const metadata: Metadata = { title: "Isolation Observatory" };
export default function Page() {
  return <ObservatoryPage />;
}
