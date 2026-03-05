import React from "react";
import "./SessionControls.css";

export default function SessionControls({ onNewSession, onReset, isConnected }) {
  return (
    <div className="session-controls">
      <button type="button" onClick={onNewSession} disabled={!isConnected}>
        New Chat
      </button>
      <button type="button" onClick={onReset} disabled={!isConnected}>
        Clear
      </button>
    </div>
  );
}
