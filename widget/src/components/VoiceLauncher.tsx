import { useEffect, useRef, useState } from "preact/hooks";
import { MicIcon, SpinnerIcon } from "../icons";
import { VoiceRecorder } from "../voiceCapture";

interface VoiceLauncherProps {
  position: "left" | "right";
  agentName: string;
  /** True while a previously-recorded turn is being transcribed/answered
   * (chat.isSending) — shown as a spinner, distinct from this button's own
   * "recording" state. */
  disabled: boolean;
  onRecordingComplete: (audio: Blob, filename: string) => void;
  onError: (message: string) => void;
}

/** A floating button separate from the chat bubble, so voice is its own
 * visible entry point — deliberately does NOT open the chat panel; it
 * records and plays the spoken reply entirely on its own (see App.tsx's
 * audioRef), matching the request that clicking the mic never pops the
 * chatbot window open.
 *
 * One click starts listening and the turn ends on its own once the visitor
 * stops talking (autoStopOnSilence) — how a voice assistant is expected to
 * behave. Clicking again still cuts the turn short immediately, so there's
 * always a manual way out (and a keyboard-reachable one). The in-panel
 * MicButton keeps the explicit press-to-stop model on purpose. */
export function VoiceLauncher({ position, agentName, disabled, onRecordingComplete, onError }: VoiceLauncherProps) {
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<VoiceRecorder | null>(null);

  useEffect(() => {
    return () => {
      recorderRef.current?.cancel();
    };
  }, []);

  async function handleClick() {
    if (disabled) return;

    if (recording) {
      recorderRef.current?.stop().catch((err: unknown) => {
        onError(err instanceof Error ? err.message : "Could not finish recording.");
      });
      return;
    }

    const recorder = new VoiceRecorder({ autoStopOnSilence: true });
    try {
      await recorder.start();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not access the microphone.");
      return;
    }
    recorderRef.current = recorder;
    setRecording(true);
    void recorder.completion?.then((blob) => {
      if (recorderRef.current !== recorder) return;
      recorderRef.current = null;
      setRecording(false);
      onRecordingComplete(blob, recorder.filename);
    });
  }

  const processing = disabled && !recording;
  const label = recording
    ? "Listening — sends automatically when you stop speaking"
    : processing
      ? "Processing…"
      : `Talk to ${agentName}`;

  return (
    <button
      type="button"
      class={`va-voice-launcher va-pos-${position}${recording ? " va-voice-recording" : ""}`}
      disabled={processing}
      onClick={handleClick}
      aria-label={label}
      aria-pressed={recording}
    >
      {processing ? <SpinnerIcon /> : <MicIcon />}
    </button>
  );
}
