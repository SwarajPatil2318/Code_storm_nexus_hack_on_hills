"use client";
import { resetIdentityNavigation } from "@/lib/operator-api";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  Crosshair,
  Fingerprint,
  Hexagon,
  Info,
  KeyRound,
  LoaderCircle,
  ShieldCheck,
  Users,
} from "lucide-react";
import { operatorRequest } from "@/lib/operator-api";
import { parseSession, roleLabels } from "@/lib/auth-types";
import type { components } from "@/lib/api.generated";
import { Badge, Button } from "./ui";
type Demo = components["schemas"]["DemoConfigResponse"];
const icons = {
  RED_OPERATOR: Crosshair,
  BLUE_OPERATOR: ShieldCheck,
  AUDITOR: Fingerprint,
  ADMIN: Users,
};
export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [demo, setDemo] = useState<Demo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    operatorRequest<Demo>("/auth/demo", { signal: controller.signal })
      .then(setDemo)
      .catch(() => {
        /* Login reports a service error on submission; demo hints are optional. */
      });
    return () => controller.abort();
  }, []);
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const csrf = await operatorRequest<{ csrf_token: string }>("/auth/csrf");
      parseSession(
        await operatorRequest("/auth/login", {
          method: "POST",
          csrf: csrf.csrf_token,
          body: { email, password },
        }),
      );
      setPassword("");
      resetIdentityNavigation("/");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign in failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <div className="login-story">
        <Link href="/login" className="brand">
          <Hexagon size={31} /> NEXUS<span className="brand-period">.</span>
        </Link>
        <Badge tone="blue">LIGHT FORENSIC INTELLIGENCE</Badge>
        <h1>
          Clarity at every
          <br />
          <span>boundary.</span>
        </h1>
        <p>
          A secure application workspace for the people testing, defending, and auditing AI systems.
        </p>
        <div className="login-boundaries">
          <span>
            <Crosshair size={17} />
            Red domain
          </span>
          <span>
            <ShieldCheck size={17} />
            Blue domain
          </span>
          <span>
            <Fingerprint size={17} />
            Audit domain
          </span>
        </div>
        <div className="login-claim">
          <Info size={17} />
          <p>
            Versioned campaigns use the Reference Monitor and explicit model identities. Local CPU
            inference runs in restricted containers when available; mocks remain clearly labelled.
          </p>
        </div>
      </div>
      <section className="login-card" aria-label="Operator sign in">
        <span className="login-key">
          <KeyRound size={22} />
        </span>
        <div className="eyebrow">AUTHENTICATED WORKSPACE</div>
        <h2>Welcome to NEXUS</h2>
        <p>Sign in with your assigned operator identity.</p>
        {demo?.enabled && (
          <div className="demo-identities">
            <div className="form-label">Development identities</div>
            <div className="demo-role-grid">
              {demo.identities.map((identity) => {
                const Icon = icons[identity.role];
                return (
                  <button
                    type="button"
                    key={identity.role}
                    aria-pressed={email === identity.email}
                    onClick={() => {
                      setEmail(identity.email);
                      setPassword("");
                    }}
                  >
                    <Icon size={17} />
                    <span>{roleLabels[identity.role]}</span>
                  </button>
                );
              })}
            </div>
            <p>
              Choose a development role, then enter its assigned operator password. Each sign-in is
              verified by the backend.
            </p>
          </div>
        )}
        <form onSubmit={submit} className="operator-form">
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="operator@example.com"
            maxLength={320}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            maxLength={256}
            placeholder="Enter your operator password"
          />
          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <ArrowRight size={16} />}
            {busy ? "Verifying identity…" : "Sign in to workspace"}
          </Button>
        </form>
        <p className="login-security">
          <ShieldCheck size={14} />
          Expiring server sessions · HttpOnly cookies · CSRF protection
        </p>
      </section>
      <span className="login-footer">NEXUS / Application authorization foundation</span>
    </main>
  );
}
