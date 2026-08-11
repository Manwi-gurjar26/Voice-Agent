import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceRecorder, isVoiceCaptureSupported } from "./voiceCapture";

type Listener = (event: { data: Blob }) => void;

class FakeMediaRecorder {
  static supportedTypes = new Set(["audio/webm;codecs=opus", "audio/webm"]);
  static isTypeSupported(type: string): boolean {
    return FakeMediaRecorder.supportedTypes.has(type);
  }

  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  private listeners: Record<string, Listener[]> = {};

  constructor(
    public stream: MediaStream,
    options: { mimeType: string },
  ) {
    this.mimeType = options.mimeType;
  }

  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    if (this.state !== "recording") throw new DOMException("already stopped", "InvalidStateError");
    this.state = "inactive";
    const data = new Blob(["fake-audio"], { type: this.mimeType });
    this.listeners.dataavailable?.forEach((listener) => listener({ data }));
    this.listeners.stop?.forEach((listener) => listener({ data }));
  }
}

function fakeTrack() {
  return { stop: vi.fn() };
}

/** Drives silence detection: `level` is the RMS the analyser should report,
 * settable per-tick so a test can script "speech, then silence". */
function fakeAudioContext() {
  const state = { level: 0, closed: false };
  class FakeAudioContext {
    state: AudioContextState = "running";
    close = vi.fn(() => {
      state.closed = true;
      return Promise.resolve();
    });
    resume = vi.fn(() => Promise.resolve());
    createMediaStreamSource() {
      return { connect: vi.fn() };
    }
    createAnalyser() {
      return {
        fftSize: 2048,
        getByteTimeDomainData: (array: Uint8Array) => {
          // A constant offset from the 128 centre yields exactly that RMS.
          array.fill(128 + Math.round(state.level * 128));
        },
      };
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return state;
}

function fakeStream() {
  const tracks = [fakeTrack(), fakeTrack()];
  return { getTracks: () => tracks, __tracks: tracks } as unknown as MediaStream & {
    __tracks: ReturnType<typeof fakeTrack>[];
  };
}

describe("voiceCapture", () => {
  let getUserMedia: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    getUserMedia = vi.fn().mockImplementation(() => Promise.resolve(fakeStream()));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  describe("isVoiceCaptureSupported", () => {
    it("is true when both getUserMedia and MediaRecorder exist", () => {
      expect(isVoiceCaptureSupported()).toBe(true);
    });

    it("is false when MediaRecorder is missing", () => {
      vi.stubGlobal("MediaRecorder", undefined);
      expect(isVoiceCaptureSupported()).toBe(false);
    });

    it("is false when getUserMedia is missing", () => {
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {},
      });
      expect(isVoiceCaptureSupported()).toBe(false);
    });
  });

  describe("VoiceRecorder", () => {
    it("start() requests the microphone and picks a supported mime type", async () => {
      const recorder = new VoiceRecorder();
      await recorder.start();
      expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
      expect(recorder.filename).toBe("recording.webm");
    });

    it("start() throws when no candidate mime type is supported", async () => {
      FakeMediaRecorder.supportedTypes = new Set();
      const recorder = new VoiceRecorder();
      await expect(recorder.start()).rejects.toThrow(/no supported audio/i);
      FakeMediaRecorder.supportedTypes = new Set(["audio/webm;codecs=opus", "audio/webm"]);
    });

    it("start() throws when the browser doesn't support recording at all", async () => {
      vi.stubGlobal("MediaRecorder", undefined);
      const recorder = new VoiceRecorder();
      await expect(recorder.start()).rejects.toThrow(/not supported/i);
    });

    it("start() propagates a getUserMedia rejection (e.g. permission denied)", async () => {
      getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
      const recorder = new VoiceRecorder();
      await expect(recorder.start()).rejects.toThrow();
    });

    it("stop() resolves with a Blob and releases the microphone tracks", async () => {
      const stream = fakeStream();
      getUserMedia.mockResolvedValue(stream);
      const recorder = new VoiceRecorder();
      await recorder.start();

      const blob = await recorder.stop();
      expect(blob).toBeInstanceOf(Blob);
      expect(blob.size).toBeGreaterThan(0);
      stream.__tracks.forEach((track) => expect(track.stop).toHaveBeenCalled());
    });

    it("stop() without an active recording rejects", async () => {
      const recorder = new VoiceRecorder();
      await expect(recorder.stop()).rejects.toThrow(/no active recording/i);
    });

    it("completion resolves the same way whether stop() is called or not, once it fires", async () => {
      const recorder = new VoiceRecorder();
      await recorder.start();
      const completion = recorder.completion;
      expect(completion).not.toBeNull();

      const stopped = await recorder.stop();
      const completed = await completion;
      expect(completed).toBe(stopped);
    });

    it("cancel() releases the microphone and never resolves completion", async () => {
      vi.useFakeTimers();
      const stream = fakeStream();
      getUserMedia.mockResolvedValue(stream);
      const recorder = new VoiceRecorder();
      await recorder.start();

      let resolved = false;
      void recorder.completion?.then(() => {
        resolved = true;
      });

      recorder.cancel();
      await vi.advanceTimersByTimeAsync(200_000);
      expect(resolved).toBe(false);
      stream.__tracks.forEach((track) => expect(track.stop).toHaveBeenCalled());
    });

    it("auto-stops after the recording cap and resolves completion", async () => {
      vi.useFakeTimers();
      const recorder = new VoiceRecorder();
      await recorder.start();

      const completionPromise = recorder.completion;
      await vi.advanceTimersByTimeAsync(120_000);

      const blob = await completionPromise;
      expect(blob).toBeInstanceOf(Blob);
    });

    it("stop() called after the auto-stop cap already fired returns the same result", async () => {
      vi.useFakeTimers();
      const recorder = new VoiceRecorder();
      await recorder.start();
      await vi.advanceTimersByTimeAsync(120_000);

      const blob = await recorder.stop();
      expect(blob).toBeInstanceOf(Blob);
    });
  });

  describe("VoiceRecorder auto-stop on silence", () => {
    it("finishes the turn once the speaker goes quiet", async () => {
      vi.useFakeTimers();
      const audio = fakeAudioContext();
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      let done = false;
      void recorder.completion?.then(() => {
        done = true;
      });

      audio.level = 0.2; // speaking
      await vi.advanceTimersByTimeAsync(1_000);
      expect(done).toBe(false);

      audio.level = 0; // stopped speaking
      await vi.advanceTimersByTimeAsync(1_000); // under the 1.5s silence window
      expect(done).toBe(false);

      await vi.advanceTimersByTimeAsync(600);
      expect(done).toBe(true);
    });

    it("keeps listening through short pauses between words", async () => {
      vi.useFakeTimers();
      const audio = fakeAudioContext();
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      let done = false;
      void recorder.completion?.then(() => {
        done = true;
      });

      for (let i = 0; i < 5; i += 1) {
        audio.level = 0.2;
        await vi.advanceTimersByTimeAsync(400);
        audio.level = 0; // a beat between words, well under the silence window
        await vi.advanceTimersByTimeAsync(800);
      }
      expect(done).toBe(false);
    });

    it("works in a noisy room, where a fixed threshold would never hear silence", async () => {
      // Ambient noise sits ABOVE the old fixed 0.015 threshold — a fan, AC, a
      // hissy laptop mic. Previously the level never dropped "below silence",
      // so the turn never ended and the visitor had to tap again.
      vi.useFakeTimers();
      const audio = fakeAudioContext();
      audio.level = 0.06; // room tone, nobody speaking
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      let done = false;
      void recorder.completion?.then(() => {
        done = true;
      });

      await vi.advanceTimersByTimeAsync(500); // let the floor be measured
      audio.level = 0.4; // speaking, well above the room tone
      await vi.advanceTimersByTimeAsync(800);
      expect(done).toBe(false);

      audio.level = 0.06; // back to just room tone = finished speaking
      await vi.advanceTimersByTimeAsync(1_700);
      expect(done).toBe(true);
      expect(recorder.speechDetected).toBe(true);
    });

    it("hears a quiet microphone whose speech never reaches the fixed threshold", async () => {
      vi.useFakeTimers();
      const audio = fakeAudioContext();
      audio.level = 0.001; // near-silent mic
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      let done = false;
      void recorder.completion?.then(() => {
        done = true;
      });

      await vi.advanceTimersByTimeAsync(300);
      audio.level = 0.02; // quiet speech, but 20x the noise floor
      await vi.advanceTimersByTimeAsync(800);
      audio.level = 0.001;
      await vi.advanceTimersByTimeAsync(1_700);

      expect(done).toBe(true);
      expect(recorder.speechDetected).toBe(true);
    });

    it("gives up if the visitor never says anything", async () => {
      vi.useFakeTimers();
      fakeAudioContext(); // stays at level 0 throughout
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      let done = false;
      void recorder.completion?.then(() => {
        done = true;
      });

      await vi.advanceTimersByTimeAsync(7_000);
      expect(done).toBe(false);

      await vi.advanceTimersByTimeAsync(1_500);
      expect(done).toBe(true);
    });

    it("closes the audio context when the recording ends", async () => {
      vi.useFakeTimers();
      const audio = fakeAudioContext();
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      await recorder.stop();
      expect(audio.closed).toBe(true);
    });

    it("still records normally when the Web Audio API is unavailable", async () => {
      vi.stubGlobal("AudioContext", undefined);
      const recorder = new VoiceRecorder({ autoStopOnSilence: true });
      await recorder.start();

      const blob = await recorder.stop();
      expect(blob).toBeInstanceOf(Blob);
    });

    it("does not watch the mic level unless asked to", async () => {
      vi.useFakeTimers();
      const audio = fakeAudioContext();
      const recorder = new VoiceRecorder(); // no autoStopOnSilence
      await recorder.start();

      let done = false;
      void recorder.completion?.then(() => {
        done = true;
      });

      audio.level = 0; // silent the whole time
      await vi.advanceTimersByTimeAsync(30_000);
      expect(done).toBe(false); // only the 120s hard cap applies
    });
  });
});
