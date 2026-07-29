// Browser microphone capture (Step 7) — kept separate from api.ts (HTTP) and
// useChat.ts (state), the same way storage.ts and sse.ts are each scoped to
// one browser concern.

// Ordered by preference: opus-in-webm is small and broadly supported
// (Chrome/Firefox/Edge); Safari (both macOS and iOS) needs mp4/AAC instead.
const CANDIDATE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

// Hard cap on a single recording — bounds upload size and STT/TTS provider
// cost per turn, independent of whether the visitor remembers to stop.
const MAX_RECORDING_MS = 120_000;

const MIME_TO_EXTENSION: Record<string, string> = {
  "audio/webm": "webm",
  "audio/mp4": "mp4",
};

export function isVoiceCaptureSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof window !== "undefined" &&
    typeof window.MediaRecorder === "function"
  );
}

function pickMimeType(): string | null {
  for (const candidate of CANDIDATE_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return null;
}

function extensionFor(mimeType: string): string {
  const base = mimeType.split(";")[0] ?? mimeType;
  return MIME_TO_EXTENSION[base] ?? "webm";
}

export class VoiceRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private autoStopTimer: ReturnType<typeof setTimeout> | null = null;
  private mimeType = "";
  private cancelled = false;

  // Created once at start() and resolved by the single native "stop"
  // listener, regardless of what triggers it (a manual stop() call, the
  // auto-stop timer, or a page/tab-level interruption) — so a caller that
  // wants to react to completion without necessarily being the one who
  // called stop() (see MicButton's auto-stop handling) can just await
  // `completion` once, instead of racing two different resolution paths.
  private stopPromise: Promise<Blob> | null = null;

  /** Filename to send the recorded Blob under — extension matches the
   * MIME type actually chosen, which Whisper needs to decode it correctly. */
  filename = "recording.webm";

  /** Resolves with the recorded audio whenever this recording ends — from a
   * manual stop(), the auto-stop cap, or an external interruption. Null
   * before start() has completed. Never resolves after cancel(). */
  get completion(): Promise<Blob> | null {
    return this.stopPromise;
  }

  async start(): Promise<void> {
    if (!isVoiceCaptureSupported()) {
      throw new Error("Voice recording is not supported in this browser.");
    }
    const mimeType = pickMimeType();
    if (!mimeType) {
      throw new Error("No supported audio recording format is available.");
    }
    this.mimeType = mimeType;
    this.filename = `recording.${extensionFor(mimeType)}`;
    this.cancelled = false;

    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];
    const recorder = new MediaRecorder(this.stream, { mimeType });
    this.recorder = recorder;

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    });

    this.stopPromise = new Promise<Blob>((resolve) => {
      recorder.addEventListener(
        "stop",
        () => {
          const blob = new Blob(this.chunks, { type: this.mimeType });
          this.releaseStream();
          if (!this.cancelled) resolve(blob);
        },
        { once: true },
      );
    });

    recorder.start();
    this.autoStopTimer = setTimeout(() => {
      if (this.recorder?.state === "recording") this.recorder.stop();
    }, MAX_RECORDING_MS);
  }

  /** Stops recording and resolves with the captured audio (same promise as
   * `completion`). Safe to call even if the recording already ended (e.g.
   * the auto-stop cap already fired) — returns the same settled result. */
  stop(): Promise<Blob> {
    // this.recorder is nulled by releaseStream() once the native "stop"
    // event has already fired (e.g. the auto-stop cap beat the caller to
    // it) — stopPromise is the source of truth for whether a completed
    // recording still exists to return, not this.recorder's presence.
    if (!this.stopPromise) {
      return Promise.reject(new Error("No active recording to stop."));
    }
    if (this.recorder?.state === "recording") this.recorder.stop();
    return this.stopPromise;
  }

  /** Discards the in-progress recording — `completion` never resolves. */
  cancel(): void {
    this.cancelled = true;
    if (this.recorder?.state === "recording") {
      this.recorder.stop();
    } else {
      this.releaseStream();
    }
  }

  private releaseStream(): void {
    if (this.autoStopTimer !== null) {
      clearTimeout(this.autoStopTimer);
      this.autoStopTimer = null;
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
  }
}
