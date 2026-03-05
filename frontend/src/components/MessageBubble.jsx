import React from "react";
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

export default function MessageBubble({ role, content, isStreaming }) {
  const isAssistant = role === "assistant";
  return (
    <div className={`bubble-row ${isAssistant ? "assistant-row" : "user-row"}`}>
      {isAssistant && <div className="bot-avatar">N</div>}
      <div className={`bubble ${isAssistant ? "assistant-bubble" : "user-bubble"}`}>
        <span>{renderBold(content)}</span>
        {isStreaming && isAssistant ? <span className="cursor">|</span> : null}
      </div>
    </div>
  );
}
