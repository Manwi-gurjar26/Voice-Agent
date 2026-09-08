"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { AlertCircle, Mic, MessagesSquare, Pencil, Plus, Trash2, Type } from "lucide-react";
import { deleteAgent, formatApiError, listAgents } from "@/lib/api";
import type { AgentRead } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/status-chip";
import { VoiceOrb } from "@/components/visuals/voice-orb";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

function SkeletonCard() {
  return (
    <div className="border-rule h-44 overflow-hidden border">
      <div className="animate-shimmer h-full w-full" />
    </div>
  );
}

/** Derived entirely from the already-loaded agent list — deliberately no
 * extra request, and no tenant-level numbers, so this stays a summary of
 * what is on screen rather than a second source of truth. The Overview page
 * is where the real, server-aggregated figures live. */
function StatStrip({ agents }: { agents: AgentRead[] }) {
  const stats = [
    { label: "Agents", value: agents.length },
    { label: "Live", value: agents.filter((a) => a.status === "active").length },
    { label: "Voice enabled", value: agents.filter((a) => a.voice_enabled).length },
  ];
  return (
    <dl className="grid grid-cols-3 gap-px">
      {stats.map(({ label, value }) => (
        <div key={label} className="border-rule border px-4 py-3">
          <dt className="eyebrow">{label}</dt>
          <dd className="mono-fig mt-1.5 text-2xl leading-none font-semibold tracking-tight">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentRead[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AgentRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await listAgents();
        if (!cancelled) setAgents(response.items);
      } catch (err) {
        if (!cancelled) setLoadError(formatApiError(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteAgent(pendingDelete.id);
      setAgents((prev) => (prev ? prev.filter((a) => a.id !== pendingDelete.id) : prev));
      toast.success(`"${pendingDelete.name}" deleted.`);
      setPendingDelete(null);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-2xl font-bold">Agents</h1>
          <p className="text-fg-dim mt-1 text-xs">
            Each agent is one embeddable chat and voice assistant.
          </p>
        </div>
        <Button
          render={<Link href="/agents/new" />}
          nativeButton={false}
          className="bg-primary text-primary-foreground hover:bg-primary/85 h-9 gap-1.5 px-3"
        >
          <Plus className="size-4" aria-hidden="true" />
          New agent
        </Button>
      </header>

      {loadError && (
        <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-3 rounded-md border p-4 text-sm">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{loadError}</p>
        </div>
      )}

      {agents === null && !loadError && (
        <div className="grid gap-px sm:grid-cols-2 xl:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {agents !== null && agents.length === 0 && (
        <div className="border-rule relative flex flex-col items-center gap-6 overflow-hidden border border-dashed px-6 py-16 text-center">
          <VoiceOrb size={170} className="animate-float" />
          <div>
            <p className="text-base font-semibold">No agents yet.</p>
            <p className="text-fg-dim mx-auto mt-1.5 max-w-sm text-xs">
              Create one, point it at your website, and paste a single script tag to put it live.
            </p>
          </div>
          <Button
            render={<Link href="/agents/new" />}
            nativeButton={false}
            className="bg-primary text-primary-foreground hover:bg-primary/85 gap-1.5"
          >
            <Plus className="size-4" aria-hidden="true" />
            Create your first agent
          </Button>
        </div>
      )}

      {agents !== null && agents.length > 0 && <StatStrip agents={agents} />}

      {agents !== null && agents.length > 0 && (
        <div className="grid gap-px sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent, i) => (
            <article
              key={agent.id}
              className="border-rule hover:border-rule-strong animate-reveal flex h-full flex-col border transition-colors"
              style={{ animationDelay: `${Math.min(i, 8) * 45}ms` }}
            >
              <div className="flex items-start justify-between gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-[13px] font-semibold">{agent.name}</h2>
                  <p className="text-fg-faint mono-fig mt-1 truncate text-[10px]">
                    {agent.public_key}
                  </p>
                </div>
                <StatusChip status={agent.status} />
              </div>

              <div className="flex flex-wrap gap-1.5 px-4 pb-4">
                <span className="border-rule text-fg-dim inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px]">
                  <Type className="size-2.5" aria-hidden="true" />
                  Chat
                </span>
                {agent.voice_enabled && (
                  <span className="border-primary/40 text-primary inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px]">
                    <Mic className="size-2.5" aria-hidden="true" />
                    Voice
                  </span>
                )}
                <span className="border-rule text-fg-faint mono-fig inline-flex max-w-full items-center truncate rounded border px-1.5 py-0.5 text-[10px]">
                  {agent.model}
                </span>
              </div>

              <div className="text-fg-faint mt-auto flex items-center justify-between gap-2 border-t px-2 py-1.5 text-[10px]">
                <span className="pl-2">
                  Updated{" "}
                  {new Date(agent.updated_at).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                  })}
                </span>
                <span className="flex gap-0.5">
                  <Button
                    render={<Link href="/playground" />}
                    nativeButton={false}
                    variant="ghost"
                    size="sm"
                    className="text-fg-dim hover:text-foreground gap-1.5"
                  >
                    <MessagesSquare className="size-3.5" aria-hidden="true" />
                    Try
                  </Button>
                  <Button
                    render={<Link href={`/agents/${agent.id}`} />}
                    nativeButton={false}
                    variant="ghost"
                    size="sm"
                    className="text-fg-dim hover:text-foreground gap-1.5"
                  >
                    <Pencil className="size-3.5" aria-hidden="true" />
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-fg-dim hover:text-destructive gap-1.5"
                    onClick={() => setPendingDelete(agent)}
                  >
                    <Trash2 className="size-3.5" aria-hidden="true" />
                    Delete
                  </Button>
                </span>
              </div>
            </article>
          ))}
        </div>
      )}

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &quot;{pendingDelete?.name}&quot;?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the agent and its embed key. Any site still embedding it
              will stop working immediately. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={deleting} onClick={() => void confirmDelete()}>
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
