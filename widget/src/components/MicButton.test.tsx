import { fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MicButton } from "./MicButton";

type Listener = (event: { data: Blob }) => void;

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
  }

  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    this.state = "inactive";
    const data = new Blob(["fake-audio"], { type: this.mimeType });
    this.listeners.dataavailable?.forEach((listener) => listener({ data }));
    this.listeners.stop?.forEach((listener) => listener({ data }));
  }
}

function fakeStream() {
  return { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
}

describe("MicButton", () => {
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
  });

  it("renders nothing when voice capture isn't supported", () => {
    vi.stubGlobal("MediaRecorder", undefined);
    const { container } = render(
      <MicButton disabled={false} onRecordingComplete={vi.fn()} onError={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("tap to start then tap to stop calls onRecordingComplete with a Blob", async () => {
    const onRecordingComplete = vi.fn();
    render(<MicButton disabled={false} onRecordingComplete={onRecordingComplete} onError={vi.fn()} />);

    const button = screen.getByLabelText("Record a voice message");
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByLabelText(/Stop recording/)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/Stop recording/));

    await waitFor(() => expect(onRecordingComplete).toHaveBeenCalledTimes(1));
    const [blob, filename] = onRecordingComplete.mock.calls[0] ?? [];
    expect(blob).toBeInstanceOf(Blob);
    expect(filename).toBe("recording.webm");
  });

  it("surfaces a getUserMedia rejection via onError instead of throwing", async () => {
    getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const onError = vi.fn();
    render(<MicButton disabled={false} onRecordingComplete={vi.fn()} onError={onError} />);

    fireEvent.click(screen.getByLabelText("Record a voice message"));

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Record a voice message")).toBeInTheDocument();
  });

  it("disabled prevents starting a recording", () => {
    render(<MicButton disabled onRecordingComplete={vi.fn()} onError={vi.fn()} />);
    const button = screen.getByLabelText("Record a voice message");
    expect(button).toBeDisabled();
  });
});
