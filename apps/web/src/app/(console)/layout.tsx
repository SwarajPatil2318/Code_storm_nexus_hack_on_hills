import { redirect } from "next/navigation";
import Link from "next/link";
import { serverSession } from "@/lib/server-api";
import { Shell } from "@/components/shell";
import type { OperatorSession } from "@/lib/auth-types";
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  let session: OperatorSession | null;
  try {
    session = await serverSession();
  } catch {
    return (
      <main className="login-page">
        <div className="login-card">
          <h1>Identity service unavailable</h1>
          <p>Your session could not be verified. Start the API and reload this page.</p>
          <Link className="button button-primary" href="/login">
            Return to sign in
          </Link>
        </div>
      </main>
    );
  }
  if (!session) redirect("/login");
  return <Shell session={session}>{children}</Shell>;
}
