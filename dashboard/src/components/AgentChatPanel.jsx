import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Send, X, Bot, User, Wrench, ChevronDown, CheckCircle, Brain, Target, Info, ShieldCheck } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, AgentChatSocket } from '../api';
import '../App.css';

function parseBadges(content) {
  if (typeof content !== 'string') return content;
  // Clean up any stray LaTeX math artifacts
  const clean = content.replace(/\\text\{([^}]+)\}/g, '$1').replace(/\$/g, '');

  const parts = clean.split(/(\[[MPSRCH](?:,\s*[MPSRCH])*\])/g);
  if (parts.length === 1) return clean;

  const badgeColors = {
    M: { bg: '#dbeafe', color: '#1e40af', label: 'Measured Telemetry' },
    P: { bg: '#f3e8ff', color: '#6b21a8', label: 'Physics / AI Prediction' },
    S: { bg: '#e0e7ff', color: '#3730a3', label: 'Plant Standard' },
    R: { bg: '#d1fae5', color: '#065f46', label: 'Statutory Regulation' },
    C: { bg: '#fee2e2', color: '#991b1b', label: 'Causal Cut (CP-SAT)' },
    H: { bg: '#fef3c7', color: '#92400e', label: 'Human Authorization' },
  };

  return parts.map((part, idx) => {
    if (/^\[[MPSRCH](?:,\s*[MPSRCH])*\]$/.test(part)) {
      const tags = part.slice(1, -1).split(',').map((s) => s.trim());
      return (
        <span key={idx} style={{ display: 'inline-flex', gap: '3px', margin: '0 3px', verticalAlign: 'baseline' }}>
          {tags.map((tag, tIdx) => {
            const b = badgeColors[tag] || { bg: '#f1f5f9', color: '#475569', label: tag };
            return (
              <span
                key={tIdx}
                title={b.label}
                style={{
                  backgroundColor: b.bg,
                  color: b.color,
                  fontSize: '10px',
                  fontWeight: 700,
                  padding: '1px 5px',
                  borderRadius: '3px',
                  border: `1px solid ${b.color}33`,
                  letterSpacing: '0.02em',
                }}
              >
                [{tag}]
              </span>
            );
          })}
        </span>
      );
    }
    return part;
  });
}

function FormattedMessage({ text }) {
  if (!text) return null;

  return (
    <div className="agent-markdown-content" style={{ fontSize: '13px', lineHeight: '1.6', color: '#1e293b' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 style={{ fontSize: '15px', fontWeight: 700, margin: '8px 0 4px', color: '#0f172a' }}>{children}</h1>,
          h2: ({ children }) => <h2 style={{ fontSize: '14px', fontWeight: 700, margin: '8px 0 4px', color: '#0f172a' }}>{children}</h2>,
          h3: ({ children }) => <h3 style={{ fontSize: '13px', fontWeight: 700, margin: '6px 0 3px', color: '#0f172a' }}>{children}</h3>,
          p: ({ children }) => (
            <p style={{ margin: '0 0 6px', lineHeight: '1.55' }}>
              {Array.isArray(children) ? children.map((c) => (typeof c === 'string' ? parseBadges(c) : c)) : typeof children === 'string' ? parseBadges(children) : children}
            </p>
          ),
          ul: ({ children }) => <ul style={{ margin: '3px 0 6px', paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '3px' }}>{children}</ul>,
          ol: ({ children }) => <ol style={{ margin: '3px 0 6px', paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '3px' }}>{children}</ol>,
          li: ({ children }) => (
            <li style={{ lineHeight: '1.5' }}>
              {Array.isArray(children) ? children.map((c) => (typeof c === 'string' ? parseBadges(c) : c)) : typeof children === 'string' ? parseBadges(children) : children}
            </li>
          ),
          strong: ({ children }) => <strong style={{ fontWeight: 600, color: '#0f172a' }}>{children}</strong>,
          hr: () => <hr style={{ border: 'none', borderTop: '1px solid #e2e8f0', margin: '8px 0' }} />,
          code: ({ children }) => <code style={{ backgroundColor: '#f1f5f9', padding: '2px 5px', borderRadius: '3px', fontSize: '11px', fontFamily: 'monospace' }}>{children}</code>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export default function AgentChatPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([{
    id: 'msg-welcome',
    sender: 'assistant',
    text: 'Hello, I am CausalCut AI, your intelligent plant assistant. How can I help you today?',
    timestamp: new Date().toISOString()
  }]);
  const [inputText, setInputText] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    // Generate a random session ID on mount
    setSessionId('sess-' + Math.random().toString(36).substring(2, 9));
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSend = async () => {
    if (!inputText.trim()) return;
    
    const userMsg = {
      id: 'msg-' + Date.now(),
      sender: 'user',
      text: inputText,
      timestamp: new Date().toISOString()
    };
    
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setIsTyping(true);
    
    try {
      const response = await api.agentChat(sessionId, userMsg.text);
      const assistantText = response?.response || response?.message || (typeof response === 'string' ? response : 'I received your query.');
      setMessages(prev => [...prev, {
        id: 'msg-' + Date.now(),
        sender: 'assistant',
        text: assistantText,
        timestamp: new Date().toISOString()
      }]);
    } catch (e) {
      console.error('Chat error:', e);
      setMessages(prev => [...prev, {
        id: 'msg-err-' + Date.now(),
        sender: 'system',
        text: 'Error communicating with Agentic AI. Please ensure the backend is running.',
        timestamp: new Date().toISOString()
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const quickAction = (action) => {
    setInputText(action);
    setTimeout(() => {
      handleSend();
    }, 50);
  };

  if (!isOpen) {
    return (
      <div 
        className="chat-floating-btn"
        onClick={() => setIsOpen(true)}
        style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          width: '56px',
          height: '56px',
          backgroundColor: 'var(--accent-orange, #ea580c)',
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'white',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          cursor: 'pointer',
          zIndex: 50
        }}
      >
        <MessageSquare size={24} />
      </div>
    );
  }

  return (
    <div 
      className="chat-panel-container"
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        width: '400px',
        height: '500px',
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: '8px',
        boxShadow: '0 10px 25px rgba(0,0,0,0.1)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 50,
        overflow: 'hidden'
      }}
    >
      <div className="chat-header" style={{
        backgroundColor: '#121d2b',
        color: '#ffffff',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '2px solid #ea580c'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Brain size={18} color="#ea580c" />
          <span style={{ fontWeight: 600, fontSize: '14px', letterSpacing: '0.5px' }}>CAUSALCUT AI</span>
        </div>
        <button 
          onClick={() => setIsOpen(false)}
          style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
        >
          <X size={18} />
        </button>
      </div>

      <div className="chat-messages" style={{
        flex: 1,
        padding: '16px',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        backgroundColor: '#f8fafc'
      }}>
        {messages.map((msg) => (
          <div 
            key={msg.id} 
            style={{
              display: 'flex',
              flexDirection: msg.sender === 'user' ? 'row-reverse' : 'row',
              gap: '10px',
              alignItems: 'flex-start'
            }}
          >
            <div style={{
              width: '28px',
              height: '28px',
              borderRadius: '50%',
              backgroundColor: msg.sender === 'user' ? '#ea580c' : '#1e293b',
              color: '#ffffff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0
            }}>
              {msg.sender === 'user' ? <User size={14} /> : <Bot size={14} />}
            </div>
            
            <div style={{
              maxWidth: '80%',
              padding: '10px 14px',
              borderRadius: '6px',
              backgroundColor: msg.sender === 'user' ? '#fff7ed' : '#ffffff',
              border: msg.sender === 'user' ? '1px solid #fed7aa' : '1px solid #e2e8f0',
              color: '#0f172a',
              fontSize: '13px',
              lineHeight: 1.5,
              position: 'relative'
            }}>
              <FormattedMessage text={msg.text} />
            </div>
          </div>
        ))}
        
        {isTyping && (
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: '#1e293b', color: '#ffffff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Wrench size={14} />
            </div>
            <div style={{
              padding: '10px 14px',
              borderRadius: '6px',
              backgroundColor: '#ffffff',
              border: '1px solid #e2e8f0',
              fontSize: '13px',
              display: 'flex',
              gap: '4px',
              alignItems: 'center'
            }}>
              <span className="dot-pulse" style={{ width: '6px', height: '6px', backgroundColor: '#94a3b8', borderRadius: '50%', animation: 'pulse 1.5s infinite' }}></span>
              <span className="dot-pulse" style={{ width: '6px', height: '6px', backgroundColor: '#94a3b8', borderRadius: '50%', animation: 'pulse 1.5s infinite 0.2s' }}></span>
              <span className="dot-pulse" style={{ width: '6px', height: '6px', backgroundColor: '#94a3b8', borderRadius: '50%', animation: 'pulse 1.5s infinite 0.4s' }}></span>
              <span style={{ color: '#64748b', marginLeft: '6px', fontSize: '11px' }}>Agent is working...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-quick-actions" style={{
        padding: '10px 16px',
        backgroundColor: '#ffffff',
        borderTop: '1px solid #f1f5f9',
        display: 'flex',
        gap: '8px',
        overflowX: 'auto',
        whiteSpace: 'nowrap'
      }}>
        <button onClick={() => quickAction("Check zone status")} style={quickBtnStyle}>Zone Status</button>
        <button onClick={() => quickAction("Run risk check")} style={quickBtnStyle}>Risk Check</button>
        <button onClick={() => quickAction("Check compliance")} style={quickBtnStyle}>Compliance</button>
      </div>

      <div className="chat-input-area" style={{
        padding: '12px 16px',
        backgroundColor: '#ffffff',
        borderTop: '1px solid #e2e8f0',
        display: 'flex',
        gap: '10px'
      }}>
        <input 
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask CausalCut AI..."
          style={{
            flex: 1,
            padding: '10px 12px',
            border: '1px solid #cbd5e1',
            borderRadius: '4px',
            fontSize: '13px',
            outline: 'none',
            fontFamily: 'inherit'
          }}
          disabled={isTyping}
        />
        <button 
          onClick={handleSend}
          disabled={!inputText.trim() || isTyping}
          style={{
            backgroundColor: (inputText.trim() && !isTyping) ? '#ea580c' : '#e2e8f0',
            color: (inputText.trim() && !isTyping) ? '#ffffff' : '#94a3b8',
            border: 'none',
            borderRadius: '4px',
            width: '40px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: (inputText.trim() && !isTyping) ? 'pointer' : 'not-allowed',
            transition: 'background-color 0.2s'
          }}
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}

const quickBtnStyle = {
  backgroundColor: '#f1f5f9',
  border: '1px solid #e2e8f0',
  borderRadius: '16px',
  padding: '6px 12px',
  fontSize: '11px',
  fontWeight: 600,
  color: '#475569',
  cursor: 'pointer'
};
