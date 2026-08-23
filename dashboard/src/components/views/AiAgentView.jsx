import React, { useEffect, useRef, useState } from "react";
import {
  Bot,
  Send,
  ShieldAlert,
  Loader2,
  Wrench,
  Sparkles,
  MessageSquare,
  Zap,
  RotateCcw,
} from "lucide-react";
import { api } from "../../api";
import "./AiAgentView.css";

/**
 * Full-page Agentic AI view — renders in the main content area when
 * the operator clicks "AI Agent" in the sidebar.
 *
 * Same read-only boundary as ChatDrawer: the backend agent can only
 * report, explain and simulate — never approve or dispatch.
 */

const SUGGESTIONS = [
  { text: "What's the current status of all zones?", icon: Zap },
  { text: "Explain the current causal-cut recommendation", icon: Sparkles },
  { text: "Any workers out of PPE compliance right now?", icon: ShieldAlert },
  { text: "How healthy are the models right now?", icon: Bot },
  { text: "Show me the active risk paths", icon: MessageSquare },
  { text: "What regulatory rules apply to zone-1?", icon: Wrench },
];

/* ---- Inline Markdown renderer (same as ChatDrawer) ---- */

function parseInline(text) {
  if (!text) return text;
  const parts = [];
  const regex = /(\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`|\*(.+?)\*|_(.+?)_)/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    if (match[2] || match[3])
      parts.push(<strong key={match.index}>{match[2] || match[3]}</strong>);
    else if (match[4])
      parts.push(
        <code key={match.index} className="agent-inline-code">
          {match[4]}
        </code>
      );
    else if (match[5] || match[6])
      parts.push(<em key={match.index}>{match[5] || match[6]}</em>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
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

    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;
      elements.push(
        <pre key={`code-${i}`} className="agent-code-block">
          {lang && <span className="agent-code-lang">{lang}</span>}
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    if (/^[-*_]{3,}\s*$/.test(trimmed)) {
      elements.push(<hr key={`hr-${i}`} className="agent-hr" />);
      i++;
      continue;
    }

    if (trimmed.startsWith("### ")) {
      elements.push(
        <h4 key={`h3-${i}`} className="agent-h3">
          {parseInline(trimmed.slice(4))}
        </h4>
      );
      i++;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      elements.push(
        <h3 key={`h2-${i}`} className="agent-h2">
          {parseInline(trimmed.slice(3))}
        </h3>
      );
      i++;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      elements.push(
        <h3 key={`h1-${i}`} className="agent-h1">
          {parseInline(trimmed.slice(2))}
        </h3>
      );
      i++;
      continue;
    }

    if (trimmed.startsWith("> ")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        quoteLines.push(lines[i].trim().slice(2));
        i++;
      }
      elements.push(
        <blockquote key={`bq-${i}`} className="agent-blockquote">
          {quoteLines.map((ql, qi) => (
            <span key={qi}>
              {parseInline(ql)}
              <br />
            </span>
          ))}
        </blockquote>
      );
      continue;
    }

    if (/^\s*[-*•]\s+/.test(line)) {
      const listItems = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        const indent = lines[i].match(/^(\s*)/)[1].length;
        const content = lines[i].replace(/^\s*[-*•]\s+/, "");
        listItems.push({ indent, content });
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="agent-list">
          {listItems.map((item, li) => (
            <li
              key={li}
              style={
                item.indent > 2
                  ? { marginLeft: `${Math.min(item.indent * 4, 24)}px` }
                  : undefined
              }
            >
              {parseInline(item.content)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const listItems = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const content = lines[i].replace(/^\s*\d+\.\s+/, "");
        listItems.push(content);
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} className="agent-list agent-ol">
          {listItems.map((item, li) => (
            <li key={li}>{parseInline(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    if (trimmed === "") {
      elements.push(<div key={`sp-${i}`} className="agent-spacer" />);
      i++;
      continue;
    }

    elements.push(
      <p key={`p-${i}`} className="agent-para">
        {parseInline(trimmed)}
      </p>
    );
    i++;
  }

  return <div className="agent-formatted">{elements}</div>;
}

function ToolBadge({ name }) {
  return (
    <span className="agent-tool-badge">
      <Wrench size={11} />
      {name}
    </span>
  );
}

function ChatBubble({ role, text, toolCalls, modelUsed }) {
  const isUser = role === "user";
  return (
    <div className={`agent-bubble-row ${isUser ? "user" : "agent"}`}>
      {!isUser && (
        <div className="agent-avatar">
          <Bot size={16} />
        </div>
      )}
      <div className={`agent-bubble ${isUser ? "user" : "agent"}`}>
        {!isUser && toolCalls?.length > 0 && (
          <div className="agent-tool-row">
            {toolCalls.map((tc, i) => (
              <ToolBadge key={`${tc.name}-${i}`} name={tc.name} />
            ))}
          </div>
        )}
        {isUser ? (
          <div className="agent-bubble-text">{text}</div>
        ) : (
          <FormattedContent text={text} />
        )}
        {!isUser && modelUsed && (
          <div className="agent-model-tag">{modelUsed}</div>
        )}
      </div>
      {isUser && (
        <div className="agent-avatar user">
          <span>You</span>
        </div>
      )}
    </div>
  );
}

export default function AiAgentView() {
  const [status, setStatus] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    api.agentStatus().then(setStatus);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, busy]);

  // Auto-focus input
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

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
    } catch (e) {
      setError(`Connection error: ${e.message}`);
    }
    setBusy(false);
  };

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
    setError(null);
    inputRef.current?.focus();
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const unavailable = status && (!status.enabled || !status.configured);

  return (
    <div className="page-canvas agent-page">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <div className="breadcrumbs">AI &amp; INTELLIGENCE</div>
          <h1 className="page-title">Safety Intelligence Agent</h1>
          <p className="page-subtitle">
            Agentic AI assistant — ask about zone status, risk paths, model
            health, regulatory citations and more.
          </p>
        </div>
        {messages.length > 0 && (
          <button className="action-btn" onClick={clearChat}>
            <RotateCcw size={14} />
            New conversation
          </button>
        )}
      </div>

      {/* Chat Interface */}
      <div className="agent-chat-container">
        {/* Chat Messages Area */}
        <div className="agent-messages-area" ref={scrollRef}>
          {unavailable && (
            <div className="agent-warning-box">
              <ShieldAlert size={16} />
              <div>
                <strong>Agent not configured.</strong> Set{" "}
                <code>CAUSALCUT_AGENT_ENABLED=true</code> and{" "}
                <code>CAUSALCUT_GEMINI_API_KEY</code> on the backend to enable
                it.
              </div>
            </div>
          )}

          {!unavailable && messages.length === 0 && (
            <div className="agent-empty-state">
              <div className="agent-empty-icon-wrap">
                <div className="agent-empty-icon">
                  <Bot size={40} />
                </div>
                <div className="agent-empty-glow" />
              </div>
              <h2>CausalCut Safety Intelligence</h2>
              <p className="agent-empty-desc">
                I can read and explain live plant state, risk paths, model
                health, and regulatory citations. I can simulate scenarios but I{" "}
                <strong>cannot</strong> approve or dispatch anything — that
                authority stays with you.
              </p>
              <div className="agent-readonly-notice">
                <ShieldAlert size={13} />
                <span>Read-only access — cannot modify plant state</span>
              </div>
              <div className="agent-suggestions-grid">
                {SUGGESTIONS.map((s) => {
                  const Icon = s.icon;
                  return (
                    <button
                      key={s.text}
                      className="agent-suggestion-card"
                      onClick={() => send(s.text)}
                      disabled={busy}
                    >
                      <Icon size={16} className="agent-suggestion-icon" />
                      <span>{s.text}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <ChatBubble
              key={i}
              role={m.role}
              text={m.text}
              toolCalls={m.toolCalls}
              modelUsed={m.modelUsed}
            />
          ))}

          {busy && (
            <div className="agent-bubble-row agent">
              <div className="agent-avatar">
                <Bot size={16} />
              </div>
              <div className="agent-bubble agent agent-loading">
                <div className="agent-typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <span className="agent-loading-text">
                  Analyzing live data…
                </span>
              </div>
            </div>
          )}

          {error && <div className="agent-error-box">{error}</div>}
        </div>

        {/* Input Area */}
        <div className="agent-input-area">
          <div className="agent-input-wrapper">
            <textarea
              ref={inputRef}
              className="agent-input"
              placeholder={
                unavailable
                  ? "Agent unavailable — configure backend to enable"
                  : "Ask about zone status, risk paths, compliance, models…"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={unavailable || busy}
              rows={1}
            />
            <button
              className="agent-send-btn"
              onClick={() => send()}
              disabled={unavailable || busy || !input.trim()}
              aria-label="Send message"
            >
              <Send size={16} />
            </button>
          </div>
          <div className="agent-input-footer">
            <span>
              Powered by Gemini · Read-only · Cannot approve or dispatch
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
