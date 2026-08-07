"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { deleteAgent, formatApiError, getAgent, updateAgent } from "@/lib/api";
import type { AgentRead } from "@/lib/types";
import {
  AgentForm,
  agentToFormValues,
  formValuesToUpdate,
  type AgentFormValues,
} from "@/components/agent-form";
import { KnowledgeBase } from "@/components/knowledge-base";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export default function EditAgentPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [agent, setAgent] = useState<AgentRead | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const result = await getAgent(params.id);
        if (!cancelled) setAgent(result);
      } catch (err) {
        if (!cancelled) setLoadError(formatApiError(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  async function handleSubmit(values: AgentFormValues) {
    setSubmitting(true);
    try {
      const updated = await updateAgent(params.id, formValuesToUpdate(values));
      setAgent(updated);
      toast.success("Agent saved.");
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteAgent(params.id);
      toast.success("Agent deleted.");
      router.push("/agents");
    } catch (err) {
      toast.error(formatApiError(err));
      setDeleting(false);
    }
  }

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!agent) return <p className="text-sm text-muted-foreground">Loading agent…</p>;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{agent.name}</h1>
        <AlertDialog>
          <AlertDialogTrigger render={<Button variant="destructive" size="sm" />}>
            Delete agent
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete &quot;{agent.name}&quot;?</AlertDialogTitle>
              <AlertDialogDescription>
                This permanently deletes the agent and its embed key. Any site still embedding it
                will stop working immediately. This cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
              <AlertDialogAction disabled={deleting} onClick={() => void handleDelete()}>
                {deleting ? "Deleting…" : "Delete"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      <div className="rounded-lg border bg-muted/30 p-4">
        <p className="mb-2 text-sm font-medium">Embed snippet</p>
        <pre className="overflow-x-auto rounded bg-background p-3 text-xs">
          <code>{agent.embed_snippet}</code>
        </pre>
      </div>

      <AgentForm
        mode="edit"
        defaultValues={agentToFormValues(agent)}
        onSubmit={handleSubmit}
        submitting={submitting}
        submitLabel="Save changes"
      />

      <KnowledgeBase agentId={agent.id} />
    </div>
  );
}
