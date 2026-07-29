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
});
