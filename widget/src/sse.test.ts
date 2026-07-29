import { describe, expect, it } from "vitest";
import { parseSseStream } from "./sse";

function responseFromChunks(chunks: string[]): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index += 1;
      } else {
        controller.close();
      }
    },
  });
  return new Response(stream);
}

async function collect(response: Response) {
  const events = [];
  for await (const event of parseSseStream(response)) {
    events.push(event);
  }
  return events;
}

describe("parseSseStream", () => {
  it("parses a single complete event delivered in one chunk", async () => {
    const response = responseFromChunks(['event: delta\ndata: {"text":"hi"}\n\n']);
    const events = await collect(response);
    expect(events).toEqual([{ event: "delta", data: { text: "hi" } }]);
  });

  it("parses multiple events delivered in one chunk", async () => {
    const response = responseFromChunks([
      'event: delta\ndata: {"text":"a"}\n\nevent: delta\ndata: {"text":"b"}\n\n',
    ]);
    const events = await collect(response);
    expect(events).toEqual([
      { event: "delta", data: { text: "a" } },
      { event: "delta", data: { text: "b" } },
    ]);
  });

  it("reassembles an event split across chunk boundaries mid-line", async () => {
    const full = 'event: delta\ndata: {"text":"hello world"}\n\n';
    // Split at an arbitrary, awkward byte offset — not aligned to any
    // logical boundary in the SSE format.
    const splitPoint = 17;
    const response = responseFromChunks([full.slice(0, splitPoint), full.slice(splitPoint)]);
    const events = await collect(response);
    expect(events).toEqual([{ event: "delta", data: { text: "hello world" } }]);
  });

  it("reassembles an event split right at the \\n\\n separator", async () => {
    const response = responseFromChunks(['event: done\ndata: {"stop_reason":"end_turn"}\n', "\n"]);
    const events = await collect(response);
    expect(events).toEqual([{ event: "done", data: { stop_reason: "end_turn" } }]);
  });

  it("handles many small single-byte-ish chunks", async () => {
    const full = 'event: delta\ndata: {"text":"x"}\n\n';
    const response = responseFromChunks(full.split(""));
    const events = await collect(response);
    expect(events).toEqual([{ event: "delta", data: { text: "x" } }]);
  });

  it("yields nothing for an empty stream", async () => {
    const response = responseFromChunks([]);
    expect(await collect(response)).toEqual([]);
  });

  it("skips a malformed block instead of throwing", async () => {
    const response = responseFromChunks(["not a valid sse block at all\n\nevent: delta\n"]);
    // Second block never closes with \n\n in this input — only the first
    // (malformed) block completes, and it should be silently skipped, not
    // crash the generator.
    const events = await collect(response);
    expect(events).toEqual([]);
  });

  it("skips a block with invalid JSON in data", async () => {
    const response = responseFromChunks(["event: delta\ndata: {not json}\n\n"]);
    expect(await collect(response)).toEqual([]);
  });

  it("processes three real events across an arbitrary chunk split", async () => {
    const full =
      'event: delta\ndata: {"text":"Hel"}\n\n' +
      'event: delta\ndata: {"text":"lo!"}\n\n' +
      'event: done\ndata: {"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":2},"citations":[]}\n\n';
    const response = responseFromChunks([full.slice(0, 40), full.slice(40, 90), full.slice(90)]);
    const events = await collect(response);
    expect(events).toHaveLength(3);
    expect(events[0]).toEqual({ event: "delta", data: { text: "Hel" } });
    expect(events[1]).toEqual({ event: "delta", data: { text: "lo!" } });
    expect(events[2]?.event).toBe("done");
  });
});
