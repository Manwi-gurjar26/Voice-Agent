"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { AlertCircle, Mic, Pencil, Plus, Sparkles, Trash2, Type } from "lucide-react";
import { deleteAgent, formatApiError, listAgents } from "@/lib/api";
import type { AgentRead } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/status-chip";
import { Tilt } from "@/components/visuals/tilt";
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
    <div className="bg-card/60 h-52 overflow-hidden rounded-2xl border">
      <div className="animate-shimmer h-full w-full" />
    </div>
  );
}

/** Derived entirely from the already-loaded agent list — deliberately no
 * extra request, and no tenant-level numbers, so this stays a summary of
 * what is on screen rather than a second source of truth. */
function StatStrip({ agents }: { agents: AgentRead[] }) {
  const stats = [
    { label: "Agents", value: agents.length },
    { label: "Live", value: agents.filter((a) => a.status === "active").length },
    { label: "Voice enabled", value: agents.filter((a) => a.voice_enabled).length },
  ];
  return (
    <dl className="grid grid-cols-3 gap-3 sm:gap-5">
      {stats.map(({ label, value }) => (
        <div
          key={label}
          className="bg-card/60 elev-1 rounded-2xl border px-4 py-3.5 backdrop-blur-sm"
        >
          <dt className="text-muted-foreground text-xs">{label}</dt>
          <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</dd>
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
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Agents</h1>
          <p className="text-muted-foreground mt-1.5 text-sm">
            Each agent is one embeddable chat and voice assistant.
          </p>
        </div>
        <Button
          render={<Link href="/agents/new" />}
          className="bg-brand-gradient elev-2 h-10 border-0 text-white hover:opacity-95"
        >
          <Plus className="size-4" aria-hidden="true" />
          New agent
        </Button>
      </header>

      {loadError && (
        <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-3 rounded-xl border p-4 text-sm">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{loadError}</p>
        </div>
      )}

      {agents === null && !loadError && (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {agents !== null && agents.length === 0 && (
        <div className="relative flex flex-col items-center gap-6 overflow-hidden rounded-3xl border border-dashed px-6 py-16 text-center">
          <VoiceOrb size={180} className="animate-float" />
          <div>
            <p className="text-lg font-semibold">No agents yet.</p>
            <p className="text-muted-foreground mx-auto mt-1.5 max-w-sm text-sm">
              Create one, point it at your website, and paste a single script tag to put it
              live.
            </p>
          </div>
          <Button
            render={<Link href="/agents/new" />}
            className="bg-brand-gradient elev-2 border-0 text-white hover:opacity-95"
          >
            <Sparkles className="size-4" aria-hidden="true" />
            Create your first agent
          </Button>
        </div>
      )}

      {agents !== null && agents.length > 0 && <StatStrip agents={agents} />}

      {agents !== null && agents.length > 0 && (
        <div className="scene-3d grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent, i) => (
            <Tilt
              key={agent.id}
              className="animate-reveal h-full"
              style={{ animationDelay: `${Math.min(i, 8) * 55}ms` }}
            >
              <article className="bg-card/70 elev-2 sheen relative flex h-full flex-col overflow-hidden rounded-2xl border backdrop-blur-sm">
                <span
                  aria-hidden="true"
                  className="bg-brand-gradient absolute inset-x-0 top-0 h-1"
                />

                <div className="flex items-start gap-3 p-5 pt-6">
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-base font-semibold">{agent.name}</h2>
                    <p className="text-muted-foreground mt-1 truncate font-mono text-[11px]">
                      {agent.public_key}
                    </p>
                  </div>
                  <StatusChip status={agent.status} />
                </div>

                <div className="flex flex-wrap gap-2 px-5 pb-5">
                  <span className="bg-muted/70 text-muted-foreground inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px]">
                    <Type className="size-3" aria-hidden="true" />
                    Chat
                  </span>
                  {agent.voice_enabled && (
                    <span className="bg-primary/10 text-primary inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px]">
                      <Mic className="size-3" aria-hidden="true" />
                      Voice
                    </span>
                  )}
                  <span className="bg-muted/70 text-muted-foreground inline-flex max-w-full items-center gap-1.5 truncate rounded-lg px-2 py-1 font-mono text-[11px]">
                    {agent.model}
                  </span>
                </div>

                <div className="text-muted-foreground mt-auto flex items-center justify-between gap-2 border-t px-5 py-3 text-[11px]">
                  <span>
                    Updated{" "}
                    {new Date(agent.updated_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                  <span className="flex gap-1">
                    <Button
                      render={<Link href={`/agents/${agent.id}`} />}
                      variant="ghost"
                      size="sm"
                      className="gap-1.5"
                    >
                      <Pencil className="size-3.5" aria-hidden="true" />
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive gap-1.5"
                      onClick={() => setPendingDelete(agent)}
                    >
                      <Trash2 className="size-3.5" aria-hidden="true" />
                      Delete
                    </Button>
                  </span>
                </div>
              </article>
            </Tilt>
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
