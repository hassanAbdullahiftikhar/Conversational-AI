import React from "react";
import { useCallback, useEffect, useState } from "react";
import ChatWindow from "./components/ChatWindow";
import SessionControls from "./components/SessionControls";
import WelcomeScreen from "./components/WelcomeScreen";
import { useWebSocket } from "./hooks/useWebSocket";
import "./App.css";

const API_BASE = "/api";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [sessionToken, setSessionToken] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputValue, setInputValue] = useState("");

  const onToken = useCallback((token) => {
    setMessages((prev) => {
      if (prev.length === 0) {
        return [{ role: "assistant", content: token }];
      }
      const last = prev[prev.length - 1];
      if (last.role === "assistant") {
        const updated = [...prev];
        updated[updated.length - 1] = { ...last, content: `${last.content}${token}` };
        return updated;
      }
      return [...prev, { role: "assistant", content: token }];
    });
  }, []);

  const onDone = useCallback(() => setIsStreaming(false), []);

  const onError = useCallback((errorText) => {
    setIsStreaming(false);
    setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${errorText}` }]);
  }, []);

  const { sendMessage, isConnected } = useWebSocket({ sessionId, sessionToken, onToken, onDone, onError });

  const createSession = useCallback(async () => {
    const response = await fetch(`${API_BASE}/sessions`, { method: "POST" });
    const data = await response.json();
    setSessionId(data.session_id);
    setSessionToken(data.token || "");
  }, []);

  useEffect(() => {
    createSession().catch(() => {
      setMessages([{ role: "assistant", content: "Error: Unable to create session. Please refresh." }]);
    });
  }, [createSession]);

  const handleSend = useCallback(() => {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming || !isConnected) return;
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInputValue("");
    setIsStreaming(true);
    sendMessage(trimmed);
  }, [inputValue, isStreaming, isConnected, sendMessage]);

  const handleQuickPrompt = useCallback((prompt) => {
    if (!isConnected || isStreaming) {
      setInputValue(prompt);
      return;
    }
    setMessages((prev) => [...prev, { role: "user", content: prompt }]);
    setIsStreaming(true);
    sendMessage(prompt);
  }, [isConnected, isStreaming, sendMessage]);

  const onNewSession = async () => {
    try {
      if (sessionId) {
        await fetch(`${API_BASE}/sessions/${sessionId}`, { method: "DELETE" });
      }
      setMessages([]);
      setIsStreaming(false);
      await createSession();
    } catch {
      setMessages([{ role: "assistant", content: "Error: Unable to start a new session. Please refresh." }]);
      setIsStreaming(false);
    }
  };

  const onReset = async () => {
    if (!sessionId) return;
    try {
      await fetch(`${API_BASE}/sessions/${sessionId}/reset`, { method: "POST" });
      setMessages([]);
      setIsStreaming(false);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "Error: Unable to reset session." }]);
      setIsStreaming(false);
    }
  };

  const onInputKeyDown = (event) => {
    if (event.key === "Enter") handleSend();
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-logo">N</div>
          <div className="brand-text">
            <span className="brand-name">NexaKart</span>
            <span className="brand-tagline">Nexa AI · Customer Support</span>
          </div>
        </div>
        <div className="header-right">
          <div className={`status-badge ${isConnected ? "online" : "offline"}`}>
            <span className="status-dot" />
            {isConnected ? "Online" : "Connecting…"}
          </div>
          <SessionControls onNewSession={onNewSession} onReset={onReset} isConnected={isConnected} />
        </div>
      </header>

      {messages.length === 0 ? (
        <WelcomeScreen onQuickPrompt={handleQuickPrompt} isConnected={isConnected} />
      ) : (
        <ChatWindow messages={messages} isStreaming={isStreaming} />
      )}

      <div className="input-area">
        <div className="input-row">
          <input
            type="text"
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Ask about your order, returns, warranty, or shipping…"
            disabled={isStreaming}
          />
          <button
            type="button"
            className="send-btn"
            onClick={handleSend}
            disabled={isStreaming || !inputValue.trim() || !isConnected}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
