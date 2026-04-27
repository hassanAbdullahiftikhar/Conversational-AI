import React from "react";
import { useEffect, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import MessageBubble from "./MessageBubble";
import "./ChatWindow.css";

export default function ChatWindow({
  messages,
  isStreaming,
  partialTranscript,
  mutedResponseIds,
  onToggleMuteResponse,
  onReplayResponse,
  diagnosticsEnabled,
}) {
  const bottomRef = useRef(null);
  const prefersReducedMotion = useReducedMotion();

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
        <AnimatePresence initial={false} mode="sync">
          {messages.map((message, idx) => (
            <motion.div
              key={`${message.role}-${idx}`}
              initial={prefersReducedMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
              animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
              exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.99 }}
              transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: [0.2, 0.75, 0.2, 1] }}
            >
              <MessageBubble
                messageId={message.id}
                role={message.role}
                content={message.content}
                isStreaming={isStreaming && idx === messages.length - 1 && message.role === "assistant"}
                isMuted={message.id ? mutedResponseIds.includes(message.id) : false}
                onToggleMute={onToggleMuteResponse}
                onReplay={onReplayResponse}
              />
              {diagnosticsEnabled && message.role === "assistant" && message.diagnostics ? (
                <div className="message-diagnostics">
                  <div className="message-diagnostics-timings">
                    <span>ttft {Number(message.diagnostics?.timings?.ttft_ms || 0)}ms</span>
                    <span>pipeline {Number(message.diagnostics?.timings?.pipeline_wall_ms || 0)}ms</span>
                    <span>tool {Number(message.diagnostics?.timings?.tool_exec_ms || 0)}ms</span>
                    <span>stream {String(message.diagnostics?.timings?.llm_stream_mode || "-")}</span>
                  </div>
                  {Array.isArray(message.diagnostics?.sources) && message.diagnostics.sources.length > 0 ? (
                    <div className="message-diagnostics-sources">
                      {message.diagnostics.sources.map((source, sourceIdx) => (
                        <span key={`${source.path || "source"}-${sourceIdx}`} className="source-chip">
                          {source.source || "source"}: {source.title || source.path || "citation"}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </motion.div>
          ))}
        </AnimatePresence>
        {isStreaming && lastMessage?.role === "user" ? (
          <div className="thinking">
            <div className="bot-avatar-sm">N</div>
            <div className="thinking-copy">
              <span className="thinking-label">Assistant is working on it</span>
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
