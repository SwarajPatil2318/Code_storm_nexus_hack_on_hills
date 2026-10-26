import type { Metadata } from "next";
import { UserManagement } from "@/components/operator-workspaces";
export const metadata: Metadata = { title: "Operator Management" };
export default function Page() {
  return <UserManagement />;
}
