import type { SseEvent } from "./types";

/**
 * Parses `event: X\ndata: Y\n\n` blocks from a streaming fetch Response body
 * — the exact format app/services/chat.py's `_sse()` produces. Native
 * EventSource can't be used here: it only supports GET with no custom body,
 * and sending a message is a POST with a JSON body and an Authorization
 * header.
 *
 * Buffers partial blocks across chunk boundaries — a `\n\n` separator can
 * land anywhere relative to how the browser happens to deliver bytes, so a
 * chunk is not guaranteed to end on an event boundary.
 */
export async function* parseSseStream(response: Response): AsyncGenerator<SseEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSseBlock(block);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice("event: ".length);
    else if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (!event || !data) return null;
  try {
    // Trusting the shape here: this parses our own backend's output, whose
    // contract is enforced by the backend's own test suite, not arbitrary
    // untrusted input.
    return { event, data: JSON.parse(data) } as SseEvent;
  } catch {
    return null;
  }
}
