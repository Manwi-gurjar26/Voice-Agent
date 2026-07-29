import { render, screen, waitFor } from "@testing-library/preact";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { ApiClient } from "./api";
import type { AgentPublicConfig, SseEvent } from "./types";

const CONFIG: AgentPublicConfig = {
  name: "Acme Bot",
  greeting: "Hi! How can I help?",
  voice_enabled: false,
  theme: { position: "bottom-right", primaryColor: "#123456" },
};

async function* asyncEvents(events: SseEvent[]): AsyncGenerator<SseEvent> {
  for (const event of events) yield event;
}

function makeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    createSession: vi.fn().mockResolvedValue({ session_token: "tok", token_type: "bearer", expires_in: 3600 }),
    validateSession: vi.fn().mockResolvedValue(true),
    createConversation: vi.fn().mockResolvedValue({ id: "conv_1", created_at: "now" }),
    listMessages: vi.fn().mockResolvedValue([]),
    sendMessage: vi.fn().mockImplementation(() => asyncEvents([])),
    sendVoiceMessage: vi.fn().mockResolvedValue({
      transcript: "What are your hours?",
      message: { id: "m_voice", role: "assistant", content: "9 to 5.", citations: null, created_at: "now" },
      audio_base64: "ZmFrZQ==",
      audio_mime: "audio/mpeg",
    }),
    ...overrides,
  };
}

type Listener = (event: { data: Blob }) => void;

class FakeMediaRecorder {
  static isTypeSupported(type: string): boolean {
    return type === "audio/webm;codecs=opus";
  }

  state: "inactive" | "recording" = "inactive";
  private listeners: Record<string, Listener[]> = {};

  constructor(
    public stream: MediaStream,
    public options: { mimeType: string },
  ) {}

  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    this.state = "inactive";
    const data = new Blob(["fake-audio"], { type: this.options.mimeType });
    this.listeners.dataavailable?.forEach((listener) => listener({ data }));
    this.listeners.stop?.forEach((listener) => listener({ data }));
  }
}

function stubVoiceCapture() {
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream),
    },
  });
}

vi.mock("./api", () => ({
  createApiClient: vi.fn(),
}));

describe("App", () => {
  it("renders nothing while bootstrapping, then the launcher once ready", async () => {
    const { createApiClient } = await import("./api");
    vi.mocked(createApiClient).mockReturnValue(makeApi());

    const { container } = render(<App baseUrl="https://api.example.com" publicKey="agt_pub_1" />);

    expect(container.querySelector(".va-launcher")).not.toBeInTheDocument();
    await waitFor(() => expect(container.querySelector(".va-launcher")).toBeInTheDocument());
    expect(container.querySelector(".va-panel")).not.toBeInTheDocument();
  });

  it("renders nothing at all if config never loads", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { createApiClient } = await import("./api");
    vi.mocked(createApiClient).mockReturnValue(makeApi({ getConfig: vi.fn().mockRejectedValue(new Error("down")) }));

    const { container } = render(<App baseUrl="https://api.example.com" publicKey="agt_pub_2" />);

    await new Promise((r) => setTimeout(r, 0));
    expect(container.firstChild).toBeNull();
  });

  it("opens the panel on launcher click, showing the greeting, and closes on the close button", async () => {
    const { createApiClient } = await import("./api");
    vi.mocked(createApiClient).mockReturnValue(makeApi());
    const user = userEvent.setup();

    const { container } = render(<App baseUrl="https://api.example.com" publicKey="agt_pub_3" />);
    await waitFor(() => expect(screen.getByLabelText("Chat with Acme Bot")).toBeInTheDocument());

    await user.click(screen.getByLabelText("Chat with Acme Bot"));
    expect(screen.getByText("Hi! How can I help?")).toBeInTheDocument();

    // The panel's own close button, not the launcher (which also carries an
    // aria-label of "Close chat" while the panel is open).
    const panelCloseButton = container.querySelector(".va-close-button") as HTMLElement;
    await user.click(panelCloseButton);
    expect(screen.queryByText("Hi! How can I help?")).not.toBeInTheDocument();
  });

  it("lets a visitor type and send a message, streaming the reply into view", async () => {
    const { createApiClient } = await import("./api");
    vi.mocked(createApiClient).mockReturnValue(
      makeApi({
        sendMessage: vi.fn().mockImplementation(() =>
          asyncEvents([
            { event: "delta", data: { text: "Sure, " } },
            { event: "delta", data: { text: "I can help." } },
            {
              event: "done",
              data: { message_id: "m1", stop_reason: "end_turn", usage: { input_tokens: 1, output_tokens: 1 }, citations: [] },
            },
          ]),
        ),
      }),
    );
    const user = userEvent.setup();

    render(<App baseUrl="https://api.example.com" publicKey="agt_pub_4" />);
    await waitFor(() => expect(screen.getByLabelText("Chat with Acme Bot")).toBeInTheDocument());
    await user.click(screen.getByLabelText("Chat with Acme Bot"));

    await user.type(screen.getByLabelText("Message"), "help me");
    await user.click(screen.getByLabelText("Send message"));

    expect(screen.getByText("help me")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Sure, I can help.")).toBeInTheDocument());
  });

  it("shows an error banner when the assistant errors out", async () => {
    const { createApiClient } = await import("./api");
    vi.mocked(createApiClient).mockReturnValue(
      makeApi({
        sendMessage: vi.fn().mockImplementation(() =>
          asyncEvents([{ event: "error", data: { code: "quota_exceeded", message: "no quota" } }]),
        ),
      }),
    );
    const user = userEvent.setup();

    render(<App baseUrl="https://api.example.com" publicKey="agt_pub_5" />);
    await waitFor(() => expect(screen.getByLabelText("Chat with Acme Bot")).toBeInTheDocument());
    await user.click(screen.getByLabelText("Chat with Acme Bot"));

    await user.type(screen.getByLabelText("Message"), "hi");
    await user.click(screen.getByLabelText("Send message"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("The assistant is temporarily unavailable."),
    );
  });

  it("applies theme values as CSS custom properties on the root", async () => {
    const { createApiClient } = await import("./api");
    vi.mocked(createApiClient).mockReturnValue(makeApi());

    const { container } = render(<App baseUrl="https://api.example.com" publicKey="agt_pub_6" />);
    await waitFor(() => expect(container.querySelector(".va-root")).toBeInTheDocument());

    const root = container.querySelector(".va-root") as HTMLElement;
    expect(root.style.getPropertyValue("--va-primary")).toBe("#123456");
  });

  describe("voice", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("a full voice turn appends both bubbles and plays the reply audio", async () => {
      stubVoiceCapture();
      const playSpy = vi.spyOn(window.HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
      const { createApiClient } = await import("./api");
      const api = makeApi({
        getConfig: vi.fn().mockResolvedValue({ ...CONFIG, voice_enabled: true }),
      });
      vi.mocked(createApiClient).mockReturnValue(api);
      const user = userEvent.setup();

      render(<App baseUrl="https://api.example.com" publicKey="agt_pub_voice" />);
      await waitFor(() => expect(screen.getByLabelText("Chat with Acme Bot")).toBeInTheDocument());
      await user.click(screen.getByLabelText("Chat with Acme Bot"));

      const micButton = await screen.findByLabelText("Record a voice message");
      await user.click(micButton);
      await waitFor(() => expect(screen.getByLabelText(/Stop recording/)).toBeInTheDocument());
      await user.click(screen.getByLabelText(/Stop recording/));

      await waitFor(() => expect(screen.getByText("What are your hours?")).toBeInTheDocument());
      expect(screen.getByText("9 to 5.")).toBeInTheDocument();
      expect(playSpy).toHaveBeenCalled();
    });
  });
});
