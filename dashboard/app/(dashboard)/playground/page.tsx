"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  AlertCircle,
  ArrowRight,
  Bot,
  Loader2,
  Mic,
  Quote,
  RotateCcw,
  Send,
  Square,
  Volume2,
} from "lucide-react";
import {
  formatApiError,
  listAgents,
  listPreviewMessages,
  sendPreviewMessage,
  sendPreviewVoiceMessage,
  startPreviewConversation,
} from "@/lib/api";
import type { AgentRead, Citation } from "@/lib/types";
import { VoiceRecorder, isVoiceCaptureSupported } from "@/lib/voice-capture";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/status-chip";
import { VoiceWave } from "@/components/visuals/brand";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------------------
   The Playground runs against the real API — real retrieval, real streaming,
   real speech-to-text and text-to-speech — through /agents/{id}/preview/*.
   That endpoint exists because the widget's own routes cannot serve this
   page: they check the caller's Origin against the agent's allowlist (the
   dashboard is not on it) and refuse any agent that is not `active` (which is
   exactly the agent you want to try first).

   Consequences worth stating plainly, and repeated in the UI: a turn here
   costs a provider call and counts against the monthly message allowance,
   exactly like a visitor's would.
--------------------------------------------------------------------------- */

interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  status: "complete" | "streaming" | "failed";
  /** Object URL for a spoken reply, when this turn came back from voice. */
  audioUrl?: string;
}

type VoiceState = "idle" | "recording" | "thinking" | "speaking";

function decodeAudioToUrl(base64: string, mime: string): string {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: mime }));
}

function greetingTurn(agent: AgentRead): Turn {
  return {
    id: "greeting",
    role: "assistant",
    content: agent.greeting,
    citations: null,
    status: "complete",
  };
}

/**
 * One conversation with one agent.
 *
 * Mounted with `key={agent.id}` by the page below, so switching agents
 * remounts it with fresh state instead of an effect that watches the
 * selection and resets six pieces of state on change. That matters for
 * correctness, not just tidiness: a conversation belongs to exactly one
 * agent, so carrying a conversation id across a switch would 404 on the
 * first send.
 */
function PreviewThread({ agent }: { agent: AgentRead }) {
  const [turns, setTurns] = useState<Turn[]>(() => [greetingTurn(agent)]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [turnError, setTurnError] = useState<string | null>(null);

  const recorderRef = useRef<VoiceRecorder | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Every object URL this thread has minted. Tracked here rather than read
  // back out of `turns` at unmount, so the cleanup does not have to close
  // over render state that will be stale by the time it runs.
  const audioUrlsRef = useRef<string[]>([]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    const urls = audioUrlsRef.current;
    const recorder = recorderRef.current;
    const audio = audioRef.current;
    return () => {
      urls.forEach(URL.revokeObjectURL);
      recorder?.cancel();
      audio?.pause();
    };
  }, []);

  const ensureConversation = useCallback(async (): Promise<string> => {
    if (conversationId) return conversationId;
    const conversation = await startPreviewConversation(agent.id);
    setConversationId(conversation.id);
    return conversation.id;
  }, [agent.id, conversationId]);

  function rememberAudio(url: string): string {
    audioUrlsRef.current.push(url);
    return url;
  }

  async function handleSend(event?: React.FormEvent) {
    event?.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;

    setDraft("");
    setTurnError(null);
    setSending(true);

    const assistantId = `a-${Date.now()}`;
    setTurns((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: "user", content, citations: null, status: "complete" },
      { id: assistantId, role: "assistant", content: "", citations: null, status: "streaming" },
    ]);

    try {
      const id = await ensureConversation();
      for await (const event of sendPreviewMessage(agent.id, id, content)) {
        if (event.event === "delta") {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === assistantId ? { ...t, content: t.content + event.data.text } : t,
            ),
          );
        } else if (event.event === "done") {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === assistantId
                ? { ...t, status: "complete", citations: event.data.citations }
                : t,
            ),
          );
        } else {
          // An SSE error arrives inside a 200 response — quota exhaustion and
          // provider failures both land here, not as an HTTP status.
          setTurnError(event.data.message);
          setTurns((prev) =>
            prev.map((t) => (t.id === assistantId ? { ...t, status: "failed" } : t)),
          );
        }
      }
      // A stream that ends without a `done` event (a dropped connection mid
      // reply) would otherwise leave the caret blinking forever.
      setTurns((prev) =>
        prev.map((t) =>
          t.id === assistantId && t.status === "streaming" ? { ...t, status: "complete" } : t,
        ),
      );
    } catch (err) {
      setTurnError(formatApiError(err));
      setTurns((prev) => prev.map((t) => (t.id === assistantId ? { ...t, status: "failed" } : t)));
    } finally {
      setSending(false);
    }
  }

  async function startRecording() {
    if (!agent.voice_enabled) return;
    setTurnError(null);

    const recorder = new VoiceRecorder({ autoStopOnSilence: true });
    recorderRef.current = recorder;
    try {
      await recorder.start();
    } catch (err) {
      recorderRef.current = null;
      setTurnError(err instanceof Error ? err.message : "Could not access the microphone.");
      return;
    }
    setVoiceState("recording");

    // Resolves whichever way the recording ends — a manual stop, the silence
    // detector, or the hard duration cap — so this one path covers all three.
    const blob = await recorder.completion?.catch(() => null);
    recorderRef.current = null;
    if (!blob) {
      setVoiceState("idle");
      return;
    }
    if (!recorder.speechDetected) {
      setVoiceState("idle");
      toast.info("Didn't hear anything — try again.");
      return;
    }

    setVoiceState("thinking");
    try {
      const id = await ensureConversation();
      const reply = await sendPreviewVoiceMessage(agent.id, id, blob, recorder.filename);
      const audioUrl = reply.audio_base64
        ? rememberAudio(decodeAudioToUrl(reply.audio_base64, reply.audio_mime || "audio/mpeg"))
        : undefined;

      setTurns((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          content: reply.transcript,
          citations: null,
          status: "complete",
        },
        {
          id: reply.message.id,
          role: "assistant",
          content: reply.message.content,
          citations: reply.message.citations,
          status: "complete",
          audioUrl,
        },
      ]);

      if (!audioUrl) {
        // Synthesis failed but the text reply survived — the backend degrades
        // rather than discarding an answer it already produced.
        setVoiceState("idle");
        toast.info("Replied in text — speech synthesis was unavailable.");
        return;
      }

      setVoiceState("speaking");
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      audio.addEventListener("ended", () => setVoiceState("idle"), { once: true });
      await audio.play().catch(() => setVoiceState("idle"));
    } catch (err) {
      setVoiceState("idle");
      setTurnError(formatApiError(err));
    }
  }

  function resetThread() {
    audioRef.current?.pause();
    recorderRef.current?.cancel();
    audioUrlsRef.current.forEach(URL.revokeObjectURL);
    audioUrlsRef.current = [];
    setConversationId(null);
    setVoiceState("idle");
    setTurnError(null);
    setTurns([greetingTurn(agent)]);
  }

  async function reloadHistory() {
    if (!conversationId) return;
    try {
      const { items } = await listPreviewMessages(agent.id, conversationId);
      setTurns(
        items.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations,
          status: "complete" as const,
        })),
      );
      toast.success("Reloaded from the server.");
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  const voiceSupported = isVoiceCaptureSupported();
  const busy = sending || voiceState === "thinking";

  return (
    <section className="border-rule flex min-h-[34rem] flex-col border">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="bg-primary/15 text-primary grid size-7 shrink-0 place-items-center rounded-md">
            <VoiceWave className="h-2.5" bars={4} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[13px] font-semibold">{agent.name}</p>
            <p className="text-fg-faint mono-fig truncate text-[10px]">{agent.public_key}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {conversationId && (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="text-fg-dim"
                onClick={() => void reloadHistory()}
              >
                Reload
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-fg-dim gap-1.5"
                onClick={resetThread}
              >
                <RotateCcw className="size-3.5" aria-hidden="true" />
                New thread
              </Button>
            </>
          )}
          <StatusChip status={agent.status} />
        </div>
      </header>

      <div ref={scrollRef} className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        {turns.map((turn) => (
          <div
            key={turn.id}
            className={cn("flex", turn.role === "user" ? "justify-end" : "justify-start")}
          >
            <div
              className={cn(
                "max-w-[80%] rounded-lg px-3 py-2 text-[13px] leading-relaxed",
                turn.role === "user"
                  ? "bg-primary text-primary-foreground rounded-br-sm"
                  : "bg-secondary text-foreground rounded-bl-sm",
                turn.status === "failed" && "border-destructive/40 border",
              )}
            >
              <p className="whitespace-pre-wrap">
                {turn.content}
                {turn.status === "streaming" && (
                  <span className="animate-caret ml-0.5 inline-block">▍</span>
                )}
              </p>

              {turn.citations && turn.citations.length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {turn.citations.map((citation) => (
                    <li
                      key={citation.document_id}
                      className="border-rule text-fg-dim flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px]"
                    >
                      <Quote className="size-2.5 shrink-0" aria-hidden="true" />
                      {citation.title}
                    </li>
                  ))}
                </ul>
              )}

              {turn.audioUrl && (
                <button
                  type="button"
                  onClick={() => void new Audio(turn.audioUrl).play()}
                  className="text-fg-faint hover:text-foreground mt-2 flex items-center gap-1.5 text-[10px] transition-colors"
                >
                  <Volume2 className="size-3" aria-hidden="true" />
                  Play again
                </button>
              )}
            </div>
          </div>
        ))}

        {voiceState === "recording" && (
          <p className="text-destructive flex items-center justify-center gap-2 py-2 text-xs">
            <VoiceWave className="h-3.5" bars={7} />
            Listening — stops on its own when you go quiet.
          </p>
        )}
        {voiceState === "thinking" && (
          <p className="text-fg-faint flex items-center justify-center gap-2 py-2 text-xs">
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            Transcribing and answering…
          </p>
        )}
        {voiceState === "speaking" && (
          <p className="text-primary flex items-center justify-center gap-2 py-2 text-xs">
            <VoiceWave className="h-3.5" bars={7} />
            Speaking…
          </p>
        )}
      </div>

      {turnError && (
        <p className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-2 border-t px-4 py-2.5 text-xs">
          <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          {turnError}
        </p>
      )}

      <form onSubmit={handleSend} className="flex items-center gap-2 border-t p-3">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={voiceState === "recording" ? "Listening…" : "Ask what a visitor would ask…"}
          disabled={busy || voiceState === "recording"}
          aria-label="Message"
          className="border-rule-strong focus-visible:border-ring placeholder:text-fg-faint flex-1 rounded-md border bg-transparent px-3 py-2 text-[13px] outline-none disabled:opacity-50"
        />

        {agent.voice_enabled && voiceSupported && (
          <Button
            type="button"
            variant="outline"
            size="icon-lg"
            aria-label={voiceState === "recording" ? "Stop recording" : "Record a message"}
            disabled={busy}
            onClick={() =>
              voiceState === "recording"
                ? void recorderRef.current?.stop()
                : void startRecording()
            }
            className={cn(
              voiceState === "recording" &&
                "border-destructive/50 bg-destructive/15 text-destructive",
            )}
          >
            {voiceState === "recording" ? (
              <Square className="size-3.5 fill-current" aria-hidden="true" />
            ) : (
              <Mic className="size-4" aria-hidden="true" />
            )}
          </Button>
        )}

        <Button
          type="submit"
          size="icon-lg"
          aria-label="Send"
          disabled={busy || !draft.trim()}
          className="bg-primary text-primary-foreground"
        >
          {sending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="size-4" aria-hidden="true" />
          )}
        </Button>
      </form>
    </section>
  );
}

function AgentMeta({ agent }: { agent: AgentRead }) {
  const rows: Array<[string, string]> = [
    ["Model", agent.model],
    ["Effort", agent.effort],
    ["Voice", agent.voice_enabled ? (agent.voice_id ?? "default voice") : "off"],
    ["Max output", `${agent.max_output_tokens.toLocaleString()} tokens`],
    [
      "Origins",
      agent.allowed_origins.length ? `${agent.allowed_origins.length} allowed` : "none set",
    ],
    ["Rate limit", `${agent.rate_limit_per_minute}/min`],
  ];
  return (
    <dl className="divide-rule divide-y text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-3 py-2">
          <dt className="text-fg-faint">{label}</dt>
          <dd className="mono-fig truncate text-right" title={value}>
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function PlaygroundPage() {
  const [agents, setAgents] = useState<AgentRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((res) => {
        if (cancelled) return;
        setAgents(res.items);
        // Prefer an active agent, since that is what visitors will hit — but
        // fall back to whatever exists so a draft-only workspace still works.
        const preferred = res.items.find((a) => a.status === "active") ?? res.items[0];
        setSelectedId(preferred?.id ?? null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(formatApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = agents?.find((a) => a.id === selectedId) ?? null;
  const voiceSupported = isVoiceCaptureSupported();

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="display text-2xl font-bold">Playground</h1>
        <p className="text-fg-dim mt-1 max-w-xl text-xs">
          The real agent, the real knowledge base, the real voice pipeline — including agents
          still in draft. Each turn costs a provider call and one message from your allowance,
          exactly as a visitor&apos;s would.
        </p>
      </header>

      {loadError && (
        <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-3 rounded-md border p-4 text-sm">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{loadError}</p>
        </div>
      )}

      {agents !== null && agents.length === 0 && (
        <div className="border-rule flex flex-col items-center gap-4 border border-dashed px-6 py-16 text-center">
          <Bot className="text-fg-faint size-7" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold">Nothing to preview yet.</p>
            <p className="text-fg-dim mx-auto mt-1.5 max-w-sm text-xs">
              Create an agent, give it something to read, and it will show up here.
            </p>
          </div>
          <Button
            render={<Link href="/agents/new" />}
            nativeButton={false}
            size="sm"
            className="bg-primary text-primary-foreground gap-1.5"
          >
            Create an agent
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      )}

      {agents && agents.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
          {/* key: a remount is exactly the right reset when the agent changes. */}
          {selected && <PreviewThread key={selected.id} agent={selected} />}

          <aside className="flex min-w-0 flex-col gap-6">
            <section className="border-rule border">
              <h2 className="eyebrow border-b px-4 py-3">Agent</h2>
              <ul className="divide-rule divide-y">
                {agents.map((agent) => (
                  <li key={agent.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(agent.id)}
                      aria-current={agent.id === selectedId ? "true" : undefined}
                      className={cn(
                        "flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left transition-colors",
                        agent.id === selectedId ? "bg-secondary" : "hover:bg-secondary/50",
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-[13px]">{agent.name}</span>
                        <span className="text-fg-faint text-[10px] capitalize">
                          {agent.status}
                          {agent.voice_enabled && " · voice"}
                        </span>
                      </span>
                      {agent.id === selectedId && (
                        <span
                          className="bg-primary size-1.5 shrink-0 rounded-full"
                          aria-hidden="true"
                        />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            {selected && (
              <section className="border-rule border">
                <h2 className="eyebrow border-b px-4 py-3">Configuration</h2>
                <div className="px-4 py-1">
                  <AgentMeta agent={selected} />
                </div>
                <div className="border-t p-3">
                  <Button
                    render={<Link href={`/agents/${selected.id}`} />}
                    nativeButton={false}
                    variant="outline"
                    size="sm"
                    className="w-full"
                  >
                    Edit this agent
                  </Button>
                </div>
              </section>
            )}

            {selected && !selected.voice_enabled && (
              <p className="text-fg-faint border-rule border border-dashed p-3 text-[11px] leading-relaxed">
                Voice is off for this agent, so the mic is hidden. Turn it on from the
                agent&apos;s settings to test speech in and speech out.
              </p>
            )}
            {selected?.voice_enabled && !voiceSupported && (
              <p className="text-fg-faint border-rule border border-dashed p-3 text-[11px] leading-relaxed">
                This browser has no MediaRecorder support, so voice cannot be tested here. Text
                still works.
              </p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
