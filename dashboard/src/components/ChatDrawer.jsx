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

/* --------------------------------------------------------------------------
 * Lightweight inline Markdown renderer.
 *
 * Handles the structured output the agent typically returns:
 *   - **bold**, *italic*, `code`
 *   - ### / ## / # headings
 *   - - / * / • bullet lists  (including nested indentation)
 *   - numbered lists (1. / 2.)
 *   - > blockquotes
 *   - ``` fenced code blocks
 *   - --- / *** horizontal rules
 *   - empty lines → spacing
 *
 * No external dependency — this is intentionally tiny and safe (no
 * dangerouslySetInnerHTML, everything is React elements).
 * -------------------------------------------------------------------------- */

function parseInline(text) {
  if (!text) return text;
  const parts = [];
  // Combined regex: bold (**…** or __…__), italic (*…* or _…_), inline code (`…`)
  const regex = /(\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`|\*(.+?)\*|_(.+?)_)/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[2] || match[3]) {
      // Bold
      parts.push(<strong key={match.index}>{match[2] || match[3]}</strong>);
    } else if (match[4]) {
      // Inline code
      parts.push(<code key={match.index} className="chat-inline-code">{match[4]}</code>);
    } else if (match[5] || match[6]) {
      // Italic
      parts.push(<em key={match.index}>{match[5] || match[6]}</em>);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length === 0 ? text : parts;
}

function FormattedContent({ text }) {
  if (!text) return null;

  const lines = text.split("\n");
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // Fenced code block
    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      elements.push(
        <pre key={`code-${i}`} className="chat-code-block">
          {lang && <span className="chat-code-lang">{lang}</span>}
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    // Horizontal rule
    if (/^[-*_]{3,}\s*$/.test(trimmed)) {
      elements.push(<hr key={`hr-${i}`} className="chat-hr" />);
      i++;
      continue;
    }

    // Headings
    if (trimmed.startsWith("### ")) {
      elements.push(<h4 key={`h3-${i}`} className="chat-h3">{parseInline(trimmed.slice(4))}</h4>);
      i++;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      elements.push(<h3 key={`h2-${i}`} className="chat-h2">{parseInline(trimmed.slice(3))}</h3>);
      i++;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      elements.push(<h3 key={`h1-${i}`} className="chat-h1">{parseInline(trimmed.slice(2))}</h3>);
      i++;
      continue;
    }

    // Blockquote
    if (trimmed.startsWith("> ")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        quoteLines.push(lines[i].trim().slice(2));
        i++;
      }
      elements.push(
        <blockquote key={`bq-${i}`} className="chat-blockquote">
          {quoteLines.map((ql, qi) => <span key={qi}>{parseInline(ql)}<br /></span>)}
        </blockquote>
      );
      continue;
    }

    // Bullet list (-, *, •)
    if (/^\s*[-*•]\s+/.test(line)) {
      const listItems = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        const indent = lines[i].match(/^(\s*)/)[1].length;
        const content = lines[i].replace(/^\s*[-*•]\s+/, "");
        listItems.push({ indent, content });
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="chat-list">
          {listItems.map((item, li) => (
            <li key={li} style={item.indent > 2 ? { marginLeft: `${Math.min(item.indent * 4, 24)}px` } : undefined}>
              {parseInline(item.content)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Numbered list (1. 2. 3.)
    if (/^\s*\d+\.\s+/.test(line)) {
      const listItems = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const content = lines[i].replace(/^\s*\d+\.\s+/, "");
        listItems.push(content);
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} className="chat-list chat-ol">
          {listItems.map((item, li) => (
            <li key={li}>{parseInline(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    // Empty line → spacer
    if (trimmed === "") {
      elements.push(<div key={`sp-${i}`} className="chat-spacer" />);
      i++;
      continue;
    }

    // Plain paragraph
    elements.push(<p key={`p-${i}`} className="chat-para">{parseInline(trimmed)}</p>);
    i++;
  }

  return <div className="chat-formatted">{elements}</div>;
}

function ChatBubble({ role, text, toolCalls, modelUsed }) {
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
        {isUser ? (
          <div className="chat-bubble-text">{text}</div>
        ) : (
          <FormattedContent text={text} />
        )}
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

    try {
      const { ok, body } = await api.agentChat(message, sessionId);

      if (!ok) {
        setError(body?.detail || "The agent is unavailable right now.");
        setBusy(false);
        return;
      }

      setSessionId(body.session_id);
      setMessages((m) => [
        ...m,
        {
          role: "agent",
          text: body.reply,
          toolCalls: body.tool_calls,
          modelUsed: body.model_used,
        },
      ]);
    } catch (err) {
      console.error("Chat error:", err);
      setError("Network error: Could not reach the agent service.");
    } finally {
      setBusy(false);
    }
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
          <ChatBubble key={i} role={m.role} text={m.text} toolCalls={m.toolCalls} modelUsed={m.modelUsed} />
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
