import type { Metadata } from "next";
import { LoginForm } from "@/components/login-form";
export const metadata: Metadata = { title: "Operator sign in" };
export default function Page() {
  return <LoginForm />;
}
