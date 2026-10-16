import { useRef, useState } from "react";
import { streamChat, type Citation } from "../api/client";

interface Message {
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
}

export default function Chat({ onBalance }: { onBalance: (b: number) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const scrollDown = () => setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);

  const send = () => {
    const question = input.trim();
    if (!question || busy) return;
    setError("");
    setInput("");
    setBusy(true);
    const history: Message[] = [...messages, { role: "user", text: question, citations: [] }];
    setMessages(history);
    scrollDown();

    let answer = "";
    let citations: Citation[] = [];
    const updateAssistant = () =>
      setMessages([...history, { role: "assistant", text: answer, citations }]);

    streamChat(question, {
      citations: (c) => {
        citations = c;
        updateAssistant();
      },
      token: (t) => {
        answer += t;
        updateAssistant();
        scrollDown();
      },
      done: (info) => {
        onBalance(info.balance_after);
        setBusy(false);
        scrollDown();
      },
      error: (e) => {
        setError(e.message.includes("402") ? "Out of credits — top up on the Billing page." : e.message);
        setBusy(false);
      },
    });
  };

  return (
    <div>
      <h2>Chat</h2>
      <p className="muted">Answers are grounded in your documents. Each query costs 1 credit.</p>
      <div>
        {messages.map((m, i) => (
          <div key={i} className="chat-msg card">
            <div className="who">{m.role === "user" ? "You" : "Assistant"}</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{m.text || "…"}</div>
            {m.citations.map((c, j) => (
              <div key={j} className="citation">
                <strong>[{j + 1}] {c.filename}</strong>
                <span className="muted"> · score {c.score.toFixed(2)}</span>
                <div className="muted">{c.snippet}</div>
              </div>
            ))}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      {error && <div className="error">{error}</div>}
      <div className="row" style={{ marginTop: 12 }}>
        <input
          className="input"
          placeholder="Ask about your documents…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={busy}
        />
        <button className="btn" onClick={send} disabled={busy || !input.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
