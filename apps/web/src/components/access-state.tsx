"use client";
import { LockKeyhole } from "lucide-react";
import { useAuth } from "./auth-provider";
import { roleLabels } from "@/lib/auth-types";
import { EmptyState, TextLink } from "./ui";
export function AccessRestricted() {
  const { session } = useAuth();
  return (
    <EmptyState
      icon={LockKeyhole}
      title="This workspace is restricted"
      description={`You are signed in as ${roleLabels[session.user.role]}. This role does not have permission to use this workspace. The API enforces the same boundary.`}
    >
      <TextLink href="/">Return to Mission Control</TextLink>
    </EmptyState>
  );
}
