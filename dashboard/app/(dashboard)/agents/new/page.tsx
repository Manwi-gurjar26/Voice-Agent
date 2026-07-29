"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
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
      <h1 className="text-xl font-semibold">New agent</h1>
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
