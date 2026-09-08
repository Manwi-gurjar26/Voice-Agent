"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Mic, RotateCcw, Send } from "lucide-react";
import { VoiceWave } from "@/components/visuals/brand";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------------------
   A scripted replay of a real conversation, for visitors who are not signed
   in. Deliberately NOT wired to the API: a public page cannot hold an agent's
   credentials, and a demo that silently costs the operator a provider call
   per visitor is a bad trade. The signed-in Playground (/playground) is the
   one that runs against real agents — this is the shop window, that is the
   workshop, and the copy below says so.
--------------------------------------------------------------------------- */

interface Turn {
  role: "user" | "assistant";
  text: string;
  /** Shown under an assistant turn, exactly as a real cited reply renders. */
  cite?: string;
}

const SCRIPT: Turn[] = [
  { role: "user", text: "do you ship to germany?" },
  {
    role: "assistant",
    text: "Yes — Germany is on our EU standard rate, €4.90, and free over €60. It usually lands in 3–5 working days.",
    cite: "Shipping & returns",
  },
  { role: "user", text: "and if it doesn't fit?" },
  {
    role: "assistant",
    text: "You have 30 days from delivery. Start the return from your order page and we email you a prepaid label — first return on any order is free.",
    cite: "Shipping & returns",
  },
];

const TYPING_MS_PER_CHAR = 14;
const PAUSE_BETWEEN_TURNS = 620;

/** Word-by-word reveal. Character-by-character reads as a novelty typewriter;
 * a real streamed reply arrives in token-sized pieces, which is closer to
 * words, so this matches what the product actually looks like. */
function useScriptedConversation(playing: boolean) {
  const [turnIndex, setTurnIndex] = useState(0);
  const [revealed, setRevealed] = useState(0);
  const [done, setDone] = useState(false);

  const words = useMemo(
    () => SCRIPT.map((turn) => turn.text.split(" ")),
    [],
  );

  useEffect(() => {
    if (!playing || done) return;
    const turn = SCRIPT[turnIndex];
    if (!turn) return;

    const total = words[turnIndex].length;
    if (revealed < total) {
      const chunk = turn.role === "user" ? total : 1; // user turns appear whole
      const delay = turn.role === "user" ? 420 : TYPING_MS_PER_CHAR * 5;
      const timer = setTimeout(() => setRevealed((n) => Math.min(total, n + chunk)), delay);
      return () => clearTimeout(timer);
    }

    const timer = setTimeout(() => {
      if (turnIndex + 1 >= SCRIPT.length) setDone(true);
      else {
        setTurnIndex((i) => i + 1);
        setRevealed(0);
      }
    }, PAUSE_BETWEEN_TURNS);
    return () => clearTimeout(timer);
  }, [playing, turnIndex, revealed, done, words]);

  function restart() {
    setTurnIndex(0);
    setRevealed(0);
    setDone(false);
  }

  const visible = SCRIPT.slice(0, turnIndex + 1).map((turn, i) => ({
    ...turn,
    text: i < turnIndex ? turn.text : words[i].slice(0, revealed).join(" "),
    complete: i < turnIndex || revealed >= words[i].length,
  }));

  return { visible, done, restart };
}

export function DemoChat({ className }: { className?: string }) {
  const [mode, setMode] = useState<"text" | "voice">("text");
  const [playing, setPlaying] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { visible, done, restart } = useScriptedConversation(playing);

  // Only starts once the panel is actually on screen. A demo that has already
  // finished playing by the time you scroll to it has shown you nothing.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && setPlaying(true),
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const lastTurn = visible[visible.length - 1];
  const listening = mode === "voice" && lastTurn?.role === "user" && !lastTurn.complete;
  const speaking = mode === "voice" && lastTurn?.role === "assistant" && !lastTurn.complete;

  return (
    <div
      ref={containerRef}
      className={cn(
        "bg-card sheen relative flex flex-col overflow-hidden rounded-xl border",
        className,
      )}
    >
      {/* Panel header — mirrors the real widget's, down to the status dot. */}
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="bg-primary/15 text-primary grid size-7 shrink-0 place-items-center rounded-md">
            <VoiceWave className="h-2.5" bars={4} />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold">Northwind Support</span>
            <span className="text-fg-faint flex items-center gap-1.5 text-[10px]">
              <span className="bg-success size-1.5 rounded-full" aria-hidden="true" />
              Online
            </span>
          </span>
        </div>

        <div
          role="group"
          aria-label="Demo mode"
          className="border-rule-strong flex items-center gap-0.5 rounded-md border p-0.5"
        >
          {(["text", "voice"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              aria-pressed={mode === value}
              className={cn(
                "rounded-[4px] px-2 py-1 text-[11px] font-medium capitalize transition-colors",
                mode === value
                  ? "bg-primary text-primary-foreground"
                  : "text-fg-faint hover:text-foreground",
              )}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div className="flex min-h-[19rem] flex-col gap-3 p-4 sm:min-h-[21rem]">
        {visible.map((turn, i) => (
          <div
            key={i}
            className={cn("flex", turn.role === "user" ? "justify-end" : "justify-start")}
          >
            <div
              className={cn(
                "max-w-[85%] rounded-lg px-3 py-2 text-[13px] leading-relaxed",
                turn.role === "user"
                  ? "bg-primary text-primary-foreground rounded-br-sm"
                  : "bg-secondary text-foreground rounded-bl-sm",
              )}
            >
              <p>
                {turn.text}
                {!turn.complete && turn.role === "assistant" && (
                  <span className="animate-caret ml-0.5 inline-block">▍</span>
                )}
              </p>
              {turn.cite && turn.complete && (
                <p className="text-fg-faint mt-1.5 flex items-center gap-1.5 text-[10px]">
                  <span className="size-1 rounded-full bg-[var(--cyan)]" aria-hidden="true" />
                  From “{turn.cite}”
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Composer. Inert by design — this is a replay, and a text box that
          swallows what you type would be worse than one that says so. */}
      <div className="flex items-center gap-2 border-t p-3">
        {mode === "voice" ? (
          <div className="flex flex-1 items-center gap-3 px-1">
            <span
              className={cn(
                "grid size-9 shrink-0 place-items-center rounded-full border transition-colors",
                listening
                  ? "border-destructive/50 bg-destructive/15 text-destructive"
                  : speaking
                    ? "border-primary/50 bg-primary/15 text-primary"
                    : "text-fg-faint",
              )}
            >
              <Mic className="size-4" aria-hidden="true" />
            </span>
            <span className="text-fg-dim flex items-center gap-2.5 text-xs">
              {listening ? (
                <>
                  <VoiceWave className="text-destructive h-3" bars={7} /> Listening…
                </>
              ) : speaking ? (
                <>
                  <VoiceWave className="text-primary h-3" bars={7} /> Speaking…
                </>
              ) : (
                "Tap to talk — the reply comes back out loud."
              )}
            </span>
          </div>
        ) : (
          <div className="border-rule-strong text-fg-faint flex flex-1 items-center rounded-md border px-3 py-2 text-[13px]">
            Ask anything…
          </div>
        )}

        {done ? (
          <button
            type="button"
            onClick={restart}
            className="text-fg-dim hover:text-foreground hover:border-rule-strong flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-2 text-xs transition-colors"
          >
            <RotateCcw className="size-3.5" aria-hidden="true" />
            Replay
          </button>
        ) : (
          <span
            aria-hidden="true"
            className="bg-primary/20 text-primary/60 grid size-9 shrink-0 place-items-center rounded-md"
          >
            <Send className="size-4" />
          </span>
        )}
      </div>
    </div>
  );
}
