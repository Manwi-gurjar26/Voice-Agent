import { useEffect, useRef, useState } from "preact/hooks";
import { MicIcon, SpinnerIcon } from "../icons";
import { VoiceRecorder } from "../voiceCapture";

interface VoiceLauncherProps {
  position: "left" | "right";
  agentName: string;
  /** True while a turn is being transcribed/answered (chat.isSending) —
   * distinguishes "thinking" from "speaking", since both are periods where
   * the launcher is busy rather than listening. */
  thinking: boolean;
  /** Must resolve only once the spoken reply has finished playing — the loop
   * below uses that as its cue to reopen the mic. */
  onRecordingComplete: (audio: Blob, filename: string) => Promise<void>;
  /** Called when the conversation ends, so the agent can be cut off
   * mid-sentence rather than talking to nobody. */
  onConversationEnd: () => void;
  onError: (message: string) => void;
}

/** How many consecutive silent listens end the conversation on their own.
 * Each is capped by the recorder's no-speech timeout (~8s), so this is about
 * 24 seconds of nothing at all — long enough to think mid-conversation,
 * short enough that a forgotten tab doesn't hold the mic open forever. */
const MAX_SILENT_ROUNDS = 3;

/** A floating button separate from the chat bubble, so voice is its own
 * visible entry point — deliberately does NOT open the chat panel; it records
 * and plays spoken replies entirely on its own (see App.tsx's audioRef),
 * matching the request that clicking the mic never pops the chatbot open.
 *
 * One tap starts a *conversation*, not a single turn: listen → answer →
 * listen again, hands-free, the way talking to a person works. It ends when
 * the visitor taps again (or falls silent for a while) — never on its own
 * after one exchange. The mic is deliberately closed while the agent speaks,
 * so it never records and replies to itself.
 *
 * The in-panel MicButton keeps the one-shot press-to-stop model on purpose:
 * that one composes a message inside a text conversation, where an
 * open-ended voice loop would be surprising. */
export function VoiceLauncher({
  position,
  agentName,
  thinking,
  onRecordingComplete,
  onConversationEnd,
  onError,
}: VoiceLauncherProps) {
  const [phase, setPhase] = useState<"idle" | "listening" | "busy">("idle");

  // Refs, not state: the loop below is a long-lived async function, and
  // reading these from a stale render closure would let an ended
  // conversation keep going.
  const activeRef = useRef(false);
  const recorderRef = useRef<VoiceRecorder | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const endRef = useRef(() => {});
  endRef.current = () => {
    if (!activeRef.current) return;
    activeRef.current = false;
    recorderRef.current?.cancel();
    recorderRef.current = null;
    // Unblocks a listen that's waiting on `completion`, which cancel()
    // deliberately never resolves.
    abortRef.current?.();
    abortRef.current = null;
    setPhase("idle");
    onConversationEnd();
  };

  // Release the microphone if the widget unmounts mid-conversation.
  useEffect(() => () => endRef.current(), []);

  async function runConversation() {
    activeRef.current = true;
    let silentRounds = 0;

    while (activeRef.current) {
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      try {
        await recorder.start();
      } catch (err) {
        endRef.current();
        onError(err instanceof Error ? err.message : "Could not access the microphone.");
        return;
      }
      // The visitor may have ended things while permission was resolving.
      if (!activeRef.current) {
        recorder.cancel();
        return;
      }

      recorderRef.current = recorder;
      setPhase("listening");
      const aborted = new Promise<null>((resolve) => {
        abortRef.current = () => resolve(null);
      });
      const blob = await Promise.race([recorder.completion ?? aborted, aborted]);
      recorderRef.current = null;
      abortRef.current = null;
      if (!activeRef.current || !blob) return;

      // Nothing but room tone: say nothing back, just keep listening, the
      // way a person waiting for you to speak would.
      if (!recorder.speechDetected) {
        silentRounds += 1;
        if (silentRounds >= MAX_SILENT_ROUNDS) {
          endRef.current();
          return;
        }
        continue;
      }

      silentRounds = 0;
      setPhase("busy");
      try {
        await onRecordingComplete(blob, recorder.filename);
      } catch (err) {
        endRef.current();
        onError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
        return;
      }
    }
  }

  function handleClick() {
    if (phase !== "idle") {
      endRef.current();
      return;
    }
    void runConversation();
  }

  const speaking = phase === "busy" && !thinking;
  const label =
    phase === "listening"
      ? "Listening — tap to end the conversation"
      : phase === "busy"
        ? `${speaking ? "Speaking" : "Thinking"} — tap to end the conversation`
        : `Talk to ${agentName}`;

  const stateClass =
    phase === "listening" ? " va-voice-recording" : phase === "busy" ? " va-voice-busy" : "";

  return (
    <button
      type="button"
      class={`va-voice-launcher va-pos-${position}${stateClass}`}
      onClick={handleClick}
      aria-label={label}
      aria-pressed={phase !== "idle"}
    >
      {phase === "busy" && !speaking ? <SpinnerIcon /> : <MicIcon />}
    </button>
  );
}
