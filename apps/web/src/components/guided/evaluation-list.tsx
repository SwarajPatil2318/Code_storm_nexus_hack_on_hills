"use client";
import Link from "next/link";
import { useAuth } from "../auth-provider";
import { useResource } from "../use-resource";
import { AccessRestricted } from "../access-state";
import { Badge, Button, PageHeading, Panel } from "../ui";
import { lifecycleLabel, type Evaluation } from "@/lib/guided-evaluation";
export function EvaluationList() {
  const { session } = useAuth();
  const list = useResource<Evaluation[]>(session.user.role === "ADMIN" ? null : "/evaluations");
  if (session.user.role === "ADMIN") return <AccessRestricted />;
  return (
    <div className="guided-workspace">
      <PageHeading
        eyebrow="YOUR AUTHORIZED HISTORY"
        title="Evaluations"
        description="Resume a handoff, inspect a real run, or follow its evidence."
        action={
          session.user.role === "RED_OPERATOR" ? (
            <Link className="button button-primary" href="/attack-lab">
              Start a security test
            </Link>
          ) : session.user.role === "BLUE_OPERATOR" ? (
            <Link className="button button-primary" href="/defence-vault">
              Open approval inbox
            </Link>
          ) : undefined
        }
      />
      <Panel
        title="Authorized evaluations"
        action={<Button onClick={list.reload}>Refresh evaluations</Button>}
      >
        <div className="guided-form">
          {list.loading ? (
            <p role="status">Reading authorized records…</p>
          ) : list.error ? (
            <p role="alert">{list.error}</p>
          ) : !list.data?.length ? (
            <p>
              No evaluation is shared with this identity yet. Red creates a test; the exact Blue
              policy owner receives its approval request.
            </p>
          ) : (
            list.data.map((e) => (
              <article className="guided-request" key={e.id}>
                <div className="guided-request-heading">
                  <h3>
                    {session.user.role === "RED_OPERATOR"
                      ? e.name
                      : `Evaluation ${e.id.slice(0, 8)}`}
                  </h3>
                  <Badge>
                    {e.status === "COMMITTED"
                      ? "Committed · inspect approval"
                      : lifecycleLabel(e.status, false)}
                  </Badge>
                </div>
                <p>
                  {e.execution_mode === "isolated_docker"
                    ? "Restricted Docker configuration"
                    : "Explicit mock configuration"}{" "}
                  · {e.id.slice(0, 8)}
                </p>
                <Link className="text-link" href={`/evaluations/${e.id}`}>
                  Open evaluation →
                </Link>
              </article>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
