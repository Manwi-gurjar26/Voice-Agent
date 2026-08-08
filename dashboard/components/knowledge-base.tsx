"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { BookOpenText, FileText, Globe, Loader2, Trash2 } from "lucide-react";
import { crawlWebsite, deleteDocument, formatApiError, listDocuments } from "@/lib/api";
import type { DocumentRead, DocumentStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<DocumentStatus, string> = {
  ready: "bg-success/10 text-success ring-success/20",
  processing: "bg-warning/10 text-warning ring-warning/20",
  pending: "bg-muted text-muted-foreground ring-border",
  failed: "bg-destructive/10 text-destructive ring-destructive/20",
};

interface KnowledgeBaseProps {
  agentId: string;
}

/** Website-crawl ingestion (Firecrawl) plus the read/delete half of the
 * knowledge base — one Document per page the crawl discovers (see
 * app/models/document.py's docstring on the backend for why), so this list
 * can grow to many rows from a single crawl. Pasted-text/file-upload/
 * single-URL ingestion already exist on the backend but have no UI here
 * yet — out of scope for this feature; the API is there when that's built. */
export function KnowledgeBase({ agentId }: KnowledgeBaseProps) {
  const [documents, setDocuments] = useState<DocumentRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [limit, setLimit] = useState("20");
  const [crawling, setCrawling] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Bumped to re-run the fetch below. Keeping the request inside the effect
  // (rather than calling a component-scoped `refresh()` from both places)
  // is what lets the cancellation flag actually work, and matches how every
  // other page in this app loads data.
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const result = await listDocuments(agentId);
        if (cancelled) return;
        setDocuments(result.items);
        setLoadError(null);
      } catch (err) {
        if (!cancelled) setLoadError(formatApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [agentId, reloadToken]);

  async function handleCrawl() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setCrawling(true);
    try {
      const parsedLimit = Number(limit) || 20;
      const result = await crawlWebsite(agentId, { url: trimmed, limit: parsedLimit });
      toast.success(`Crawled ${result.items.length} page${result.items.length === 1 ? "" : "s"}.`);
      setUrl("");
      setReloadToken((token) => token + 1);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setCrawling(false);
    }
  }

  async function handleDelete(documentId: string) {
    setDeletingId(documentId);
    try {
      await deleteDocument(agentId, documentId);
      setDocuments((prev) => prev.filter((d) => d.id !== documentId));
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setDeletingId(null);
    }
  }

  const readyCount = documents.filter((d) => d.status === "ready").length;

  return (
    <section className="bg-card/60 elev-1 overflow-hidden rounded-2xl border backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div className="flex items-start gap-3">
          <span className="bg-primary/10 text-primary mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg">
            <BookOpenText className="size-4" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-sm font-semibold">Knowledge base</h2>
            <p className="text-muted-foreground text-xs">
              What the agent is allowed to answer from.
            </p>
          </div>
        </div>
        {documents.length > 0 && (
          <span className="bg-muted text-muted-foreground rounded-full px-2.5 py-1 text-[11px] font-medium tabular-nums">
            {readyCount} of {documents.length} ready
          </span>
        )}
      </div>

      <div className="flex flex-col gap-5 p-5">
        <div className="bg-muted/40 flex flex-col gap-3 rounded-xl border border-dashed p-4">
          <Label htmlFor="crawl-url" className="text-sm font-medium">
            Crawl a website
          </Label>
          <p className="text-muted-foreground -mt-1 text-xs">
            Every page found becomes part of this agent&apos;s knowledge, so it answers from
            your real content. The site has to be publicly reachable — a URL only your own
            machine can open will not work.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Globe
                className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                aria-hidden="true"
              />
              <Input
                id="crawl-url"
                placeholder="https://yourbusiness.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={crawling}
                className="h-10 pl-9"
              />
            </div>
            <Input
              aria-label="Max pages"
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              disabled={crawling}
              className="h-10 w-full tabular-nums sm:w-24"
            />
            <Button
              onClick={() => void handleCrawl()}
              disabled={crawling || !url.trim()}
              className="bg-brand-gradient elev-1 h-10 border-0 text-white hover:opacity-95"
            >
              {crawling && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
              {crawling ? "Crawling…" : "Crawl"}
            </Button>
          </div>
          {crawling && (
            <p className="text-muted-foreground text-xs">
              Larger sites can take a minute or two — please keep this page open.
            </p>
          )}
        </div>

        {loading ? (
          <p className="text-muted-foreground text-sm">Loading knowledge base…</p>
        ) : loadError ? (
          <p className="text-destructive text-sm">{loadError}</p>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <FileText className="text-muted-foreground/50 size-8" aria-hidden="true" />
            <p className="text-muted-foreground text-sm">
              No documents yet — crawl a website above to get started.
            </p>
          </div>
        ) : (
          <ul className="divide-y rounded-xl border">
            {documents.map((doc) => (
              <li key={doc.id} className="hover:bg-muted/30 flex items-center gap-3 p-3 transition-colors">
                <FileText
                  className="text-muted-foreground size-4 shrink-0"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium" title={doc.title}>
                    {doc.title}
                  </p>
                  {doc.source_url && (
                    <p className="text-muted-foreground truncate text-xs" title={doc.source_url}>
                      {doc.source_url}
                    </p>
                  )}
                  {doc.status === "failed" && doc.error_message && (
                    <p className="text-destructive mt-0.5 text-xs">{doc.error_message}</p>
                  )}
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset",
                    STATUS_STYLE[doc.status],
                  )}
                >
                  <span>{doc.status}</span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Delete ${doc.title}`}
                  disabled={deletingId === doc.id}
                  onClick={() => void handleDelete(doc.id)}
                  className="text-muted-foreground hover:text-destructive shrink-0"
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
