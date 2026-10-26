import { redirect } from "next/navigation";
import Link from "next/link";
import { serverSession } from "@/lib/server-api";
import { AuthProvider } from "@/components/auth-provider";
export default async function SecureRunLayout({ children }: { children: React.ReactNode }) {
  let session;
  try {
    session = await serverSession();
  } catch {
    return (
      <main className="login-page">
        <div className="login-card">
          <h1>Identity service unavailable</h1>
          <p>Your session could not be verified. Reload when the API is ready.</p>
          <Link href="/login">Return to sign in</Link>
        </div>
      </main>
    );
  }
  if (!session) redirect("/login");
  return <AuthProvider session={session}>{children}</AuthProvider>;
}
