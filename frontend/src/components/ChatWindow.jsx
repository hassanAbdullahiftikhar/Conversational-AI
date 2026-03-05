import React from "react";
import { useEffect, useRef } from "react";
import MessageBubble from "./MessageBubble";
import "./ChatWindow.css";

export default function ChatWindow({ messages, isStreaming }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const lastMessage = messages[messages.length - 1];

  return (
    <div className="chat-window">
      {messages.map((message, idx) => (
        <MessageBubble
          key={`${message.role}-${idx}`}
          role={message.role}
          content={message.content}
          isStreaming={isStreaming && idx === messages.length - 1 && message.role === "assistant"}
        />
      ))}
      {isStreaming && lastMessage?.role === "user" ? (
        <div className="thinking">
          <div className="bot-avatar-sm">N</div>
          <span>Nexa is thinking</span>
          <div className="thinking-dots">
            <span /><span /><span />
          </div>
        </div>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}
