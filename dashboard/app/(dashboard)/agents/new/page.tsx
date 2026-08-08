"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { createAgent, formatApiError } from "@/lib/api";
import {
  AgentForm,
  DEFAULT_AGENT_FORM_VALUES,
  formValuesToCreate,
  type AgentFormValues,
} from "@/components/agent-form";

export default function NewAgentPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(values: AgentFormValues) {
    setSubmitting(true);
    try {
      const agent = await createAgent(formValuesToCreate(values));
      toast.success(`"${agent.name}" created.`);
      router.push(`/agents/${agent.id}`);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/agents"
        className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        All agents
      </Link>

      <header>
        <h1 className="text-3xl font-semibold tracking-tight">New agent</h1>
        <p className="text-muted-foreground mt-1.5 text-sm">
          You can change any of this later — nothing here is permanent.
        </p>
      </header>

      <AgentForm
        mode="create"
        defaultValues={DEFAULT_AGENT_FORM_VALUES}
        onSubmit={handleSubmit}
        submitting={submitting}
        submitLabel="Create agent"
      />
    </div>
  );
}
