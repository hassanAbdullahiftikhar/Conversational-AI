import React from "react";
import { useEffect, useRef } from "react";
import MessageBubble from "./MessageBubble";
import "./ChatWindow.css";

export default function ChatWindow({
  messages,
  isStreaming,
  partialTranscript,
  mutedResponseIds,
  onToggleMuteResponse,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming, partialTranscript]);

  const lastMessage = messages[messages.length - 1];

  return (
    <div className="chat-window">
      <div className="chat-stream">
        {messages.length > 0 ? (
          <div className="chat-stream-intro">
            <span className="chat-stream-kicker ds-kicker">Live Conversation</span>
            <span className="chat-stream-note">Responses stream token by token and voice playback follows your active preferences.</span>
          </div>
        ) : null}
        {messages.map((message, idx) => (
          <MessageBubble
            key={`${message.role}-${idx}`}
            messageId={message.id}
            role={message.role}
            content={message.content}
            isStreaming={isStreaming && idx === messages.length - 1 && message.role === "assistant"}
            isMuted={message.id ? mutedResponseIds.includes(message.id) : false}
            onToggleMute={onToggleMuteResponse}
          />
        ))}
        {isStreaming && lastMessage?.role === "user" ? (
          <div className="thinking">
            <div className="bot-avatar-sm">N</div>
            <div className="thinking-copy">
              <span className="thinking-label">Nexa is working on it</span>
              <div className="thinking-dots">
                <span /><span /><span />
              </div>
            </div>
          </div>
        ) : null}
        {partialTranscript ? (
          <div className="partial-transcript">
            <div className="partial-transcript-header">
              <span className="partial-transcript-label">Listening</span>
              <div className="partial-transcript-wave">
                <span /><span /><span />
              </div>
            </div>
            <div className="partial-transcript-text">{partialTranscript}</div>
          </div>
        ) : null}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}
