"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { AlertCircle, ArrowLeft, Code2, Trash2 } from "lucide-react";
import { deleteAgent, formatApiError, getAgent, updateAgent } from "@/lib/api";
import type { AgentRead } from "@/lib/types";
import {
  AgentForm,
  agentToFormValues,
  formValuesToUpdate,
  type AgentFormValues,
} from "@/components/agent-form";
import { KnowledgeBase } from "@/components/knowledge-base";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { LogoMark } from "@/components/visuals/brand";
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

  if (loadError) {
    return (
      <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-3 rounded-xl border p-4 text-sm">
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p>{loadError}</p>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col gap-5">
        <div className="animate-shimmer h-28 rounded-2xl border" />
        <div className="animate-shimmer h-40 rounded-2xl border" />
      </div>
    );
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

      <header className="bg-card/60 elev-2 sheen relative overflow-hidden rounded-2xl border p-6 backdrop-blur-sm">
        <span aria-hidden="true" className="bg-brand-gradient absolute inset-x-0 top-0 h-1" />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-4">
            <LogoMark size={44} className="elev-2 mt-0.5 rounded-xl" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="truncate text-2xl font-semibold tracking-tight">{agent.name}</h1>
                <StatusChip status={agent.status} />
              </div>
              <p className="text-muted-foreground mt-1.5 font-mono text-xs break-all">
                {agent.public_key}
              </p>
            </div>
          </div>

          <AlertDialog>
            <AlertDialogTrigger
              render={<Button variant="outline" size="sm" className="text-destructive gap-1.5" />}
            >
              <Trash2 className="size-3.5" aria-hidden="true" />
              Delete agent
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete &quot;{agent.name}&quot;?</AlertDialogTitle>
                <AlertDialogDescription>
                  This permanently deletes the agent and its embed key. Any site still embedding
                  it will stop working immediately. This cannot be undone.
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
      </header>

      <section className="bg-card/60 elev-1 overflow-hidden rounded-2xl border backdrop-blur-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
          <div className="flex items-start gap-3">
            <span className="bg-primary/10 text-primary mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg">
              <Code2 className="size-4" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-sm font-semibold">Embed snippet</h2>
              <p className="text-muted-foreground text-xs">
                Paste this once, just before <code>&lt;/body&gt;</code> on your site.
              </p>
            </div>
          </div>
          <CopyButton value={agent.embed_snippet} label="Copy snippet" />
        </div>
        <div className="p-5">
          {/* Kept as a single text node so the whole snippet copies and reads
              as one unit rather than syntax-highlighted fragments. */}
          <pre className="bg-foreground/[0.04] overflow-x-auto rounded-xl border p-4 text-xs leading-relaxed">
            <code className="font-mono">{agent.embed_snippet}</code>
          </pre>
          {agent.status !== "active" && (
            <p className="text-warning mt-3 flex items-start gap-2 text-xs">
              <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              This agent is {agent.status}. Set its status to active below before embedding it —
              the widget will not load otherwise.
            </p>
          )}
        </div>
      </section>

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
