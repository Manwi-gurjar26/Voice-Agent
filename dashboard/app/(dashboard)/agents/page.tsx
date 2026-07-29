"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { deleteAgent, formatApiError, listAgents } from "@/lib/api";
import type { AgentRead } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

const STATUS_VARIANT: Record<AgentRead["status"], "default" | "secondary" | "outline"> = {
  active: "default",
  draft: "secondary",
  disabled: "outline",
};

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
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Agents</h1>
        <Button render={<Link href="/agents/new" />}>New agent</Button>
      </div>

      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      {agents === null && !loadError && (
        <p className="text-sm text-muted-foreground">Loading agents…</p>
      )}

      {agents !== null && agents.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-16 text-center">
          <p className="text-sm text-muted-foreground">No agents yet.</p>
          <Button render={<Link href="/agents/new" />} variant="outline" size="sm">
            Create your first agent
          </Button>
        </div>
      )}

      {agents !== null && agents.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {agents.map((agent) => (
              <TableRow key={agent.id}>
                <TableCell className="font-medium">{agent.name}</TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[agent.status]}>{agent.status}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{agent.model}</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(agent.updated_at).toLocaleString()}
                </TableCell>
                <TableCell className="flex justify-end gap-2 text-right">
                  <Button
                    render={<Link href={`/agents/${agent.id}`} />}
                    variant="outline"
                    size="sm"
                  >
                    Edit
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setPendingDelete(agent)}>
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
