import React, { useEffect, useRef, useState } from "react";
import { MessageSquare, X, Send, ShieldAlert, Loader2, Wrench } from "lucide-react";
import { api } from "../api";

/**
 * Agentic Chat Drawer — CausalCut Safety Intelligence.
 *
 * READ-ONLY by construction: the backend agent (see app/engine/agent_tools.py)
 * can only report, explain and simulate. It cannot approve or dispatch
 * anything — that always stays on the causal-cut approval panel. This
 * component reflects that boundary in its own copy rather than implying the
 * agent can act.
 */

const SUGGESTIONS = [
  "What's the status of zone-1?",
  "Explain the current causal-cut recommendation",
  "Any workers out of PPE compliance right now?",
  "How healthy are the models right now?",
];

function ToolBadge({ name }) {
  return (
    <span className="chat-tool-badge">
      <Wrench size={11} />
      {name}
    </span>
  );
}

function ChatBubble({ role, text, toolCalls }) {
  const isUser = role === "user";
  return (
    <div className={`chat-bubble-row ${isUser ? "user" : "agent"}`}>
      <div className={`chat-bubble ${isUser ? "user" : "agent"}`}>
        {!isUser && toolCalls?.length > 0 && (
          <div className="chat-tool-row">
            {toolCalls.map((tc, i) => (
              <ToolBadge key={`${tc.name}-${i}`} name={tc.name} />
            ))}
          </div>
        )}
        <div className="chat-bubble-text">{text}</div>
      </div>
    </div>
  );
}

export default function ChatDrawer({ open, onClose }) {
  const [status, setStatus] = useState(null); // { enabled, configured, model }
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (open) api.agentStatus().then(setStatus);
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = async (text) => {
    const message = (text ?? input).trim();
    if (!message || busy) return;

    setMessages((m) => [...m, { role: "user", text: message }]);
    setInput("");
    setBusy(true);
    setError(null);

    const { ok, body } = await api.agentChat(message, sessionId);

    if (!ok) {
      setError(body?.detail || "The agent is unavailable right now.");
      setBusy(false);
      return;
    }

    setSessionId(body.session_id);
    setMessages((m) => [...m, { role: "agent", text: body.reply, toolCalls: body.tool_calls }]);
    setBusy(false);
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  if (!open) return null;

  const unavailable = status && (!status.enabled || !status.configured);

  return (
    <div className="chat-drawer">
      <div className="chat-drawer-header">
        <div className="chat-drawer-title">
          <MessageSquare size={16} />
          <span>Safety Intelligence</span>
          <span className="chat-readonly-pill" title="This agent can only read and explain plant state — it cannot approve or dispatch anything.">
            READ-ONLY
          </span>
        </div>
        <button className="chat-close-btn" onClick={onClose} aria-label="Close chat">
          <X size={16} />
        </button>
      </div>

      <div className="chat-drawer-body" ref={scrollRef}>
        {unavailable && (
          <div className="chat-warning-box">
            <ShieldAlert size={14} />
            <div>
              Agent isn't configured on this deployment. Set{" "}
              <code>CAUSALCUT_AGENT_ENABLED=true</code> and{" "}
              <code>CAUSALCUT_GEMINI_API_KEY</code> on the backend to enable it.
            </div>
          </div>
        )}

        {!unavailable && messages.length === 0 && (
          <div className="chat-empty-state">
            <p>
              Ask about live zone status, the current causal-cut recommendation, model health, or
              regulatory citations. I can explain and simulate — I can't approve or dispatch anything.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chat-suggestion-chip" onClick={() => send(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <ChatBubble key={i} role={m.role} text={m.text} toolCalls={m.toolCalls} />
        ))}

        {busy && (
          <div className="chat-bubble-row agent">
            <div className="chat-bubble agent chat-bubble-loading">
              <Loader2 size={14} className="chat-spin" />
              <span>Checking live data…</span>
            </div>
          </div>
        )}

        {error && <div className="chat-error-box">{error}</div>}
      </div>

      <div className="chat-drawer-input-row">
        <textarea
          className="chat-input"
          placeholder={unavailable ? "Agent unavailable" : "Ask about zone status, risk, compliance…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={unavailable || busy}
          rows={1}
        />
        <button
          className="chat-send-btn"
          onClick={() => send()}
          disabled={unavailable || busy || !input.trim()}
          aria-label="Send"
        >
          <Send size={15} />
        </button>
      </div>
    </div>
  );
}
