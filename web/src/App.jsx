import { useLayoutEffect, useRef, useState } from "react";
import { consumeSse, postChat, postResume } from "./api.js";

const USERS = [
  { id: "u_alice", name: "Alice", role: "PM" },
  { id: "u_bob", name: "Bob", role: "Engineer" },
];

export default function App() {
  const [userId, setUserId] = useState("u_alice");
  const [threadId, setThreadId] = useState("");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([]);
  const [citations, setCitations] = useState([]);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef(null);

  function scrollChatToBottom() {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }

  useLayoutEffect(() => {
    scrollChatToBottom();
  }, [messages, busy, error]);

  function applyEvent(event) {
    if (event.type === "meta" && event.thread_id) {
      setThreadId(event.thread_id);
    } else if (event.type === "citations") {
      setCitations(event.citations || []);
    } else if (event.type === "interrupt") {
      setPending(event.pending || null);
    } else if (event.type === "message" && event.content) {
      setPending(null);
      setMessages((prev) => [...prev, { role: "assistant", content: event.content }]);
    }
  }

  async function runStream(request) {
    setBusy(true);
    setError("");
    try {
      const response = await request();
      await consumeSse(response, applyEvent);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setCitations([]);
    setPending(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    await runStream(() =>
      postChat({ userId, message: text, threadId: threadId || undefined })
    );
  }

  async function decide(confirmed) {
    if (!threadId || busy) return;
    await runStream(() => postResume({ userId, threadId, confirmed }));
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  const payload = pending?.payload || {};
  const isDelete = pending?.action === "delete_task";

  return (
    <div className="shell">
      <header className="top">
        <div>
          <h1>DeskAgent</h1>
          <p>Northwind Labs 工作台 · 检索带出处，写入先确认</p>
        </div>
        <label className="user">
          当前用户
          <select
            value={userId}
            disabled={busy}
            onChange={(event) => setUserId(event.target.value)}
          >
            {USERS.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} · {user.role}
              </option>
            ))}
          </select>
        </label>
      </header>

      <main className="board">
        <section className="chat">
          <h2>聊天记录</h2>
          <div className="chat-log" ref={logRef}>
            {messages.length === 0 && (
              <p className="hint">
                试试：「退款周期是多久？给出处。」、「帮我建一条待办：发货前核对收货地址」或「删除任务 t_004」
              </p>
            )}
            {messages.map((item, index) => (
              <article key={index} className={`bubble ${item.role}`}>
                <span className="who">{item.role === "user" ? "你" : "助手"}</span>
                <pre>{item.content}</pre>
              </article>
            ))}
            {busy && <p className="hint">处理中…</p>}
            {error && <p className="error">{error}</p>}
          </div>
        </section>

        <aside className="cites">
          <h2>引用</h2>
          {citations.length === 0 ? (
            <p className="hint">制度问答命中后会显示文档与摘录。查库路径保持为空。</p>
          ) : (
            citations.map((hit, index) => (
              <article key={`${hit.chunk_id}-${index}`} className="cite">
                <strong>{hit.title || hit.doc_id}</strong>
                <code>{hit.chunk_id}</code>
                <p>{hit.quote}</p>
              </article>
            ))
          )}
        </aside>
      </main>

      {pending && (
        <section className="pending">
          <div>
            <h2>{isDelete ? "待确认删除" : "待确认写入"}</h2>
            <p>{pending.message || "即将写入待办，请确认或驳回"}</p>
            <pre>{JSON.stringify(payload, null, 2)}</pre>
          </div>
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => decide(false)}>
              驳回
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => decide(true)}
            >
              {isDelete ? "确认删除" : "确认写入"}
            </button>
          </div>
        </section>
      )}

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <textarea
          rows={8}
          value={draft}
          disabled={busy || Boolean(pending)}
          placeholder={pending ? "请先确认或驳回写入" : "输入问题，Enter 发送，Shift+Enter 换行"}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="primary" disabled={busy || Boolean(pending)}>
          发送
        </button>
      </form>
    </div>
  );
}
