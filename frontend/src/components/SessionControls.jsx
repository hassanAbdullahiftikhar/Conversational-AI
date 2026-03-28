import React from "react";
import "./SessionControls.css";

export default function SessionControls({ onNewSession, onReset, isConnected }) {
  return (
    <div className="session-controls">
      <button type="button" className="session-control-button" onClick={onNewSession} disabled={!isConnected}>
        <span className="session-control-icon">+</span>
        <span>New Chat</span>
      </button>
      <button type="button" className="session-control-button ghost" onClick={onReset} disabled={!isConnected}>
        <span className="session-control-icon">x</span>
        <span>Clear</span>
      </button>
    </div>
  );
}
