async function* parseSse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) {
          yield JSON.parse(line.slice(6));
        }
      }
    }
  }
}

async function readError(response) {
  const text = await response.text();
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") return data.detail;
  } catch {
    /* not JSON */
  }
  return text || `HTTP ${response.status}`;
}

export async function consumeSse(response, onEvent) {
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  for await (const event of parseSse(response)) {
    onEvent(event);
  }
}

export function postChat({ userId, message, threadId }) {
  return fetch("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({
      message,
      thread_id: threadId || undefined,
    }),
  });
}

export function postResume({ userId, threadId, confirmed }) {
  return fetch("/chat/resume", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ thread_id: threadId, confirmed }),
  });
}
