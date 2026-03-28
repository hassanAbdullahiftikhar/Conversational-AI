import React from "react";
import { useState } from "react";
import "./MessageBubble.css";

// Simple parser to convert **bold** markdown into <strong> elements.
function renderBold(text) {
  const parts = [];
  const regex = /\*\*(.*?)\*\*/g;
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<strong key={match.index}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
  }
  parts.push(text.slice(lastIndex));
  return parts;
}

export default function MessageBubble({
  messageId,
  role,
  content,
  isStreaming,
  isMuted,
  onToggleMute,
}) {
  const isAssistant = role === "assistant";
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch (_err) {
      setCopied(false);
    }
  };

  return (
    <div className={`bubble-row ${isAssistant ? "assistant-row" : "user-row"}`}>
      {isAssistant && <div className="bot-avatar">N</div>}
      <div className={`bubble-stack ${isAssistant ? "assistant-stack" : "user-stack"}`}>
        <div className="bubble-meta">
          <span className="bubble-author">{isAssistant ? "Nexa" : "You"}</span>
          {isStreaming && isAssistant ? <span className="bubble-live">Streaming</span> : null}
        </div>
        <div className={`bubble ${isAssistant ? "assistant-bubble" : "user-bubble"}`}>
          <span>{renderBold(content)}</span>
          {isStreaming && isAssistant ? <span className="cursor">|</span> : null}
        </div>
        <div className="bubble-actions">
          <button
            type="button"
            className="bubble-copy-toggle ds-action-button ds-focus-ring"
            onClick={handleCopy}
            aria-label="Copy message"
          >
            {copied ? "Copied" : "Copy"}
          </button>
          {isAssistant && typeof onToggleMute === "function" && messageId ? (
            <button
              type="button"
              className="bubble-audio-toggle ds-action-button ds-focus-ring"
              onClick={() => onToggleMute(messageId)}
            >
              {isMuted ? "Unmute" : "Mute"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
