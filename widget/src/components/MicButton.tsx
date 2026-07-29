import { useEffect, useRef, useState } from "preact/hooks";
import { MicIcon } from "../icons";
import { VoiceRecorder, isVoiceCaptureSupported } from "../voiceCapture";

interface MicButtonProps {
  disabled: boolean;
  onRecordingComplete: (audio: Blob, filename: string) => void;
  onError: (message: string) => void;
}

export function MicButton({ disabled, onRecordingComplete, onError }: MicButtonProps) {
  const [recording, setRecording] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const recorderRef = useRef<VoiceRecorder | null>(null);

  useEffect(() => {
    if (!recording) return;
    const interval = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(interval);
  }, [recording]);

  // Release the microphone if the widget unmounts (or the panel closes)
  // while a recording is still in progress. cancel() suppresses completion,
  // so this never triggers onRecordingComplete for a discarded recording.
  useEffect(() => {
    return () => {
      recorderRef.current?.cancel();
    };
  }, []);

  // Progressive enhancement: browsers without MediaRecorder/getUserMedia
  // (or non-browser environments) simply don't get a mic button, rather
  // than a broken one.
  if (!isVoiceCaptureSupported()) return null;

  function finalize(recorder: VoiceRecorder, blob: Blob) {
    // Guards against a stale completion firing after this recorder has
    // already been superseded or cancelled.
    if (recorderRef.current !== recorder) return;
    recorderRef.current = null;
    setRecording(false);
    setElapsedSeconds(0);
    onRecordingComplete(blob, recorder.filename);
  }

  async function handleClick() {
    if (disabled) return;

    if (recording) {
      // finalize() runs from the `completion` handler below, not from this
      // await — stop() and the auto-stop cap resolve the same promise, so
      // there is exactly one finalization path for both.
      recorderRef.current?.stop().catch((err: unknown) => {
        onError(err instanceof Error ? err.message : "Could not finish recording.");
      });
      return;
    }

    const recorder = new VoiceRecorder();
    try {
      await recorder.start();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not access the microphone.");
      return;
    }
    recorderRef.current = recorder;
    setElapsedSeconds(0);
    setRecording(true);
    void recorder.completion?.then((blob) => finalize(recorder, blob));
  }

  return (
    <button
      type="button"
      class={`va-mic-button${recording ? " va-mic-recording" : ""}`}
      disabled={disabled}
      onClick={handleClick}
      aria-label={recording ? `Stop recording (${elapsedSeconds}s)` : "Record a voice message"}
      aria-pressed={recording}
    >
      <MicIcon />
    </button>
  );
}
