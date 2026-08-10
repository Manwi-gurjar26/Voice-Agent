// Browser microphone capture (Step 7) — kept separate from api.ts (HTTP) and
// useChat.ts (state), the same way storage.ts and sse.ts are each scoped to
// one browser concern.

// Ordered by preference: opus-in-webm is small and broadly supported
// (Chrome/Firefox/Edge); Safari (both macOS and iOS) needs mp4/AAC instead.
const CANDIDATE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

// Hard cap on a single recording — bounds upload size and STT/TTS provider
// cost per turn, independent of whether the visitor remembers to stop.
const MAX_RECORDING_MS = 120_000;

// --- Silence detection (opt-in via VoiceRecorderOptions.autoStopOnSilence) ---
// How often the mic level is sampled. Counted in ticks rather than wall-clock
// timestamps so the behaviour is deterministic under fake timers.
const SILENCE_POLL_MS = 100;
// RMS amplitude (0..1) at or above which the visitor is considered to be
// speaking. Room tone and mic self-noise sit well under this; normal speech
// sits well over it.
const DEFAULT_SILENCE_THRESHOLD = 0.015;
// How long the visitor must stay quiet *after having spoken* before the turn
// is considered finished. Long enough to survive the natural pauses between
// words and sentences, short enough not to feel laggy.
const DEFAULT_SILENCE_DURATION_MS = 1_500;
// Give up if the visitor never says anything at all, rather than holding the
// mic open until MAX_RECORDING_MS. The resulting near-empty recording is
// rejected by the backend with "Could not hear anything in that recording."
const DEFAULT_NO_SPEECH_TIMEOUT_MS = 8_000;

export interface VoiceRecorderOptions {
  /** Finish the recording automatically once the visitor stops speaking,
   * instead of waiting for a second stop() call. Used by the standalone
   * voice launcher, where click-to-start/click-again-to-stop doesn't match
   * how people expect a voice assistant to behave; the in-panel mic button
   * deliberately keeps the explicit press-to-stop model. */
  autoStopOnSilence?: boolean;
  silenceThreshold?: number;
  silenceDurationMs?: number;
  noSpeechTimeoutMs?: number;
}

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
  private silenceTimer: ReturnType<typeof setInterval> | null = null;
  private audioContext: AudioContext | null = null;
  private mimeType = "";
  private cancelled = false;
  private watchingLevel = false;
  private heardSpeech = false;

  constructor(private readonly options: VoiceRecorderOptions = {}) {}

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

  /** Whether anyone actually spoke during this recording. Lets a caller skip
   * uploading a recording that's certainly just room tone (see
   * VoiceLauncher's hands-free loop, which keeps listening instead).
   *
   * True when the mic level was never watched at all — without silence
   * detection there's no evidence either way, and treating "unknown" as
   * silence would drop perfectly good recordings. */
  get speechDetected(): boolean {
    return !this.watchingLevel || this.heardSpeech;
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
    this.watchingLevel = false;
    this.heardSpeech = false;

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

    if (this.options.autoStopOnSilence) this.startSilenceDetection(this.stream);
  }

  /** Watches the live mic level and ends the recording once the visitor has
   * spoken and then gone quiet. Best-effort: a browser without the Web Audio
   * API (or one that refuses to open an AudioContext) simply keeps the
   * manual stop() path, rather than failing the recording outright. */
  private startSilenceDetection(stream: MediaStream): void {
    const AudioContextCtor =
      typeof window === "undefined"
        ? undefined
        : window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (typeof AudioContextCtor !== "function") return;

    let context: AudioContext;
    let analyser: AnalyserNode;
    try {
      context = new AudioContextCtor();
      analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      context.createMediaStreamSource(stream).connect(analyser);
    } catch {
      return;
    }
    this.audioContext = context;
    this.watchingLevel = true;
    // Clicking the launcher is a user gesture, so this normally starts
    // "running" — but resume() is harmless if it already is, and rescues the
    // case where a browser hands back a suspended context anyway.
    if (context.state === "suspended") void context.resume();

    const threshold = this.options.silenceThreshold ?? DEFAULT_SILENCE_THRESHOLD;
    const silenceTicks = Math.ceil(
      (this.options.silenceDurationMs ?? DEFAULT_SILENCE_DURATION_MS) / SILENCE_POLL_MS,
    );
    const noSpeechTicks = Math.ceil(
      (this.options.noSpeechTimeoutMs ?? DEFAULT_NO_SPEECH_TIMEOUT_MS) / SILENCE_POLL_MS,
    );

    const samples = new Uint8Array(analyser.fftSize);
    let hasSpoken = false;
    let quietTicks = 0;
    let totalTicks = 0;

    this.silenceTimer = setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let sumSquares = 0;
      for (const sample of samples) {
        // Byte time-domain data is centred on 128; normalise to -1..1.
        const centred = (sample - 128) / 128;
        sumSquares += centred * centred;
      }
      const rms = Math.sqrt(sumSquares / samples.length);
      totalTicks += 1;

      if (rms >= threshold) {
        hasSpoken = true;
        this.heardSpeech = true;
        quietTicks = 0;
        return;
      }

      quietTicks += 1;
      const finished = hasSpoken ? quietTicks >= silenceTicks : totalTicks >= noSpeechTicks;
      if (finished && this.recorder?.state === "recording") this.recorder.stop();
    }, SILENCE_POLL_MS);
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
    if (this.silenceTimer !== null) {
      clearInterval(this.silenceTimer);
      this.silenceTimer = null;
    }
    if (this.audioContext) {
      // close() rejects if the context is already closed; nothing here can
      // act on that, and letting it reject unhandled would surface as a
      // console error on an otherwise successful recording.
      void this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
  }
}
