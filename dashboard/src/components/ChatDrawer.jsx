import React, { useState, useRef, useEffect } from "react";
import { X, Send, Bot, User, Loader2 } from "lucide-react";
import "./ChatDrawer.css";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1";

export default function ChatDrawer({ isOpen, onClose, factoryId }) {
  const [messages, setMessages] = useState([
    { role: "model", content: "Hello! I am CausalCut AI. How can I help you manage safety operations today?" }
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSend = async () => {
    if (!input.trim()) return;
    
    const userMsg = { role: "user", content: input };
    const newMessages = [...messages, userMsg];
    
    setMessages(newMessages);
    setInput("");
    setIsTyping(true);
    
    try {
      const res = await fetch(`${API_BASE}/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: newMessages.map(m => ({ role: m.role, content: m.content })),
          factory_id: factoryId || "unknown"
        })
      });
      
      if (!res.ok) throw new Error("Agent failed to respond.");
      
      const data = await res.json();
      setMessages(prev => [...prev, { role: "model", content: data.response }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: "model", content: "Error: Could not reach the safety agent." }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className={`chat-drawer ${isOpen ? "open" : ""}`}>
      <div className="chat-header">
        <div className="chat-header-title">
          <Bot size={20} className="chat-icon" />
          <span>CausalCut Agent</span>
        </div>
        <button className="chat-close" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === "model" ? <Bot size={16} /> : <User size={16} />}
            </div>
            <div className="message-content">
              {msg.content}
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="chat-message model typing">
            <div className="message-avatar"><Bot size={16} /></div>
            <div className="message-content">
              <Loader2 size={16} className="spin" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      
      <div className="chat-input-area">
        <textarea
          placeholder="Ask about factory safety, risks, or generate a report..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={2}
        />
        <button className="chat-send" onClick={handleSend} disabled={!input.trim() || isTyping}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
