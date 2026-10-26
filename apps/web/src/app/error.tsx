"use client";
import { TriangleAlert } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <EmptyState
      icon={TriangleAlert}
      title="This workspace could not load"
      description="Please try again. If the issue continues, inspect the local application logs."
    >
      <Button onClick={reset}>Try again</Button>
    </EmptyState>
  );
}
