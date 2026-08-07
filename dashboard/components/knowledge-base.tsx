"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { crawlWebsite, deleteDocument, formatApiError, listDocuments } from "@/lib/api";
import type { DocumentRead, DocumentStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const STATUS_VARIANT: Record<DocumentStatus, "secondary" | "outline" | "destructive"> = {
  ready: "secondary",
  processing: "outline",
  pending: "outline",
  failed: "destructive",
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

  async function refresh() {
    try {
      const result = await listDocuments(agentId);
      setDocuments(result.items);
      setLoadError(null);
    } catch (err) {
      setLoadError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  async function handleCrawl() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setCrawling(true);
    try {
      const parsedLimit = Number(limit) || 20;
      const result = await crawlWebsite(agentId, { url: trimmed, limit: parsedLimit });
      toast.success(`Crawled ${result.items.length} page${result.items.length === 1 ? "" : "s"}.`);
      setUrl("");
      await refresh();
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

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Knowledge base</h2>

      <div className="flex flex-col gap-2 rounded-lg border p-4">
        <Label htmlFor="crawl-url">Crawl a website</Label>
        <p className="text-sm text-muted-foreground">
          Enter your website&apos;s URL — every page found (up to the limit below) becomes part of
          this agent&apos;s knowledge base, so it can answer questions grounded in your site&apos;s
          real content.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="crawl-url"
            placeholder="https://yourbusiness.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={crawling}
            className="flex-1"
          />
          <Input
            aria-label="Max pages"
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            disabled={crawling}
            className="w-full sm:w-28"
          />
          <Button onClick={() => void handleCrawl()} disabled={crawling || !url.trim()}>
            {crawling ? "Crawling…" : "Crawl"}
          </Button>
        </div>
        {crawling && (
          <p className="text-xs text-muted-foreground">
            This can take a little while for larger sites — please don&apos;t close this page.
          </p>
        )}
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading knowledge base…</p>
      ) : loadError ? (
        <p className="text-sm text-destructive">{loadError}</p>
      ) : documents.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No documents yet — crawl a website above to get started.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="max-w-64 truncate" title={doc.title}>
                  {doc.title}
                </TableCell>
                <TableCell className="text-muted-foreground">{doc.source_type}</TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[doc.status]}>{doc.status}</Badge>
                  {doc.status === "failed" && doc.error_message && (
                    <p className="mt-1 text-xs text-destructive">{doc.error_message}</p>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={deletingId === doc.id}
                    onClick={() => void handleDelete(doc.id)}
                  >
                    {deletingId === doc.id ? "Deleting…" : "Delete"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
