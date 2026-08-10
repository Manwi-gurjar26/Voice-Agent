import { fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceLauncher } from "./VoiceLauncher";

type Listener = (event: { data: Blob }) => void;

/** Records itself into `active` so a test can end a recording the same way
 * silence detection would, without driving real audio levels. */
const active: { recorders: FakeMediaRecorder[] } = { recorders: [] };

class FakeMediaRecorder {
  static isTypeSupported(type: string): boolean {
    return type === "audio/webm;codecs=opus";
  }

  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  private listeners: Record<string, Listener[]> = {};

  constructor(
    public stream: MediaStream,
    options: { mimeType: string },
  ) {
    this.mimeType = options.mimeType;
    active.recorders.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    if (this.state !== "recording") return;
    this.state = "inactive";
    const data = new Blob(["fake-audio"], { type: this.mimeType });
    this.listeners.dataavailable?.forEach((l) => l({ data }));
    this.listeners.stop?.forEach((l) => l({ data }));
  }
}

/** Mic level is scripted per test: `level` drives the analyser, so a test can
 * play "someone spoke, then went quiet" and let the real silence-detection
 * code decide when the turn ends. */
const audio = { level: 0 };

class FakeAudioContext {
  state: AudioContextState = "running";
  close = vi.fn(() => Promise.resolve());
  resume = vi.fn(() => Promise.resolve());
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }
  createAnalyser() {
    return {
      fftSize: 2048,
      getByteTimeDomainData: (array: Uint8Array) => array.fill(128 + Math.round(audio.level * 128)),
    };
  }
}

function fakeStream() {
  return { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
}

/** Speak, then fall silent long enough for auto-stop to fire. */
async function speakThenPause() {
  audio.level = 0.3;
  await vi.advanceTimersByTimeAsync(500);
  audio.level = 0;
  await vi.advanceTimersByTimeAsync(2_000);
}

function renderLauncher(overrides: Partial<Parameters<typeof VoiceLauncher>[0]> = {}) {
  const props = {
    position: "right" as const,
    agentName: "Aura",
    thinking: false,
    onRecordingComplete: vi.fn().mockResolvedValue(undefined),
    onConversationEnd: vi.fn(),
    onError: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<VoiceLauncher {...props} />) };
}

describe("VoiceLauncher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    active.recorders = [];
    audio.level = 0;
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.stubGlobal("AudioContext", FakeAudioContext);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream()) },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("keeps the conversation going: one tap, then turn after turn hands-free", async () => {
    const { props } = renderLauncher();
    fireEvent.click(screen.getByLabelText("Talk to Aura"));

    await speakThenPause();
    await waitFor(() => expect(props.onRecordingComplete).toHaveBeenCalledTimes(1));

    // No second tap — the mic must reopen on its own once the reply is done.
    await vi.advanceTimersByTimeAsync(50);
    await waitFor(() => expect(screen.getByLabelText(/Listening/)).toBeInTheDocument());

    await speakThenPause();
    await waitFor(() => expect(props.onRecordingComplete).toHaveBeenCalledTimes(2));

    await vi.advanceTimersByTimeAsync(50);
    await speakThenPause();
    await waitFor(() => expect(props.onRecordingComplete).toHaveBeenCalledTimes(3));
  });

  it("does not reopen the mic until the reply has finished playing", async () => {
    let finishReply = () => {};
    const onRecordingComplete = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishReply = resolve;
        }),
    );
    renderLauncher({ onRecordingComplete });

    fireEvent.click(screen.getByLabelText("Talk to Aura"));
    await speakThenPause();
    await waitFor(() => expect(onRecordingComplete).toHaveBeenCalledTimes(1));

    // While the agent is still speaking there must be no live recorder,
    // otherwise it would record its own voice.
    const recordersWhileSpeaking = active.recorders.length;
    await vi.advanceTimersByTimeAsync(5_000);
    expect(active.recorders.length).toBe(recordersWhileSpeaking);
    expect(screen.queryByLabelText(/Listening/)).not.toBeInTheDocument();

    finishReply();
    await vi.advanceTimersByTimeAsync(50);
    await waitFor(() => expect(screen.getByLabelText(/Listening/)).toBeInTheDocument());
  });

  it("tapping again ends the conversation", async () => {
    const { props } = renderLauncher();
    fireEvent.click(screen.getByLabelText("Talk to Aura"));
    await waitFor(() => expect(screen.getByLabelText(/Listening/)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/Listening/));

    await waitFor(() => expect(screen.getByLabelText("Talk to Aura")).toBeInTheDocument());
    expect(props.onConversationEnd).toHaveBeenCalled();

    // And it stays ended — no further turns get sent.
    await speakThenPause();
    expect(props.onRecordingComplete).not.toHaveBeenCalled();
  });

  it("stays quiet and keeps listening when it hears nothing", async () => {
    const { props } = renderLauncher();
    fireEvent.click(screen.getByLabelText("Talk to Aura"));

    // One full no-speech window: nothing should be sent to the backend...
    await vi.advanceTimersByTimeAsync(8_500);
    expect(props.onRecordingComplete).not.toHaveBeenCalled();
    // ...and it should still be listening rather than having given up.
    await waitFor(() => expect(screen.getByLabelText(/Listening/)).toBeInTheDocument());
  });

  it("ends on its own after a long stretch of silence", async () => {
    const { props } = renderLauncher();
    fireEvent.click(screen.getByLabelText("Talk to Aura"));

    // Three consecutive no-speech windows (~24s).
    await vi.advanceTimersByTimeAsync(27_000);

    await waitFor(() => expect(screen.getByLabelText("Talk to Aura")).toBeInTheDocument());
    expect(props.onRecordingComplete).not.toHaveBeenCalled();
    expect(props.onConversationEnd).toHaveBeenCalled();
  });

  it("shows thinking and speaking while the agent answers", async () => {
    let finishReply = () => {};
    const onRecordingComplete = vi.fn(
      () => new Promise<void>((resolve) => (finishReply = resolve)),
    );
    const { rerender, props } = renderLauncher({ onRecordingComplete });

    fireEvent.click(screen.getByLabelText("Talk to Aura"));
    await speakThenPause();
    await waitFor(() => expect(onRecordingComplete).toHaveBeenCalled());

    rerender(<VoiceLauncher {...props} onRecordingComplete={onRecordingComplete} thinking />);
    await waitFor(() => expect(screen.getByLabelText(/Thinking/)).toBeInTheDocument());

    rerender(
      <VoiceLauncher {...props} onRecordingComplete={onRecordingComplete} thinking={false} />,
    );
    await waitFor(() => expect(screen.getByLabelText(/Speaking/)).toBeInTheDocument());
    finishReply();
  });

  it("reports a microphone permission failure and does not start a conversation", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError")) },
    });
    const { props } = renderLauncher();

    fireEvent.click(screen.getByLabelText("Talk to Aura"));
    // waitFor polls on real timers, which never advance here — flush the
    // rejection's microtasks through the fake clock instead.
    await vi.advanceTimersByTimeAsync(10);

    expect(props.onError).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Talk to Aura")).toBeInTheDocument();
  });
});
