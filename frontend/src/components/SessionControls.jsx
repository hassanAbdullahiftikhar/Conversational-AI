import React from "react";
import "./SessionControls.css";

export default function SessionControls({
  onNewSession,
  onReset,
  isConnected,
  diagnosticsEnabled = false,
  onToggleDiagnostics = null,
}) {
  return (
    <div className="session-controls">
      <button type="button" className="session-control-button ds-focus-ring" onClick={onNewSession} disabled={!isConnected}>
        <span className="session-control-icon">+</span>
        <span>New Chat</span>
      </button>
      <button type="button" className="session-control-button ghost ds-focus-ring" onClick={onReset} disabled={!isConnected}>
        <span className="session-control-icon">x</span>
        <span>Clear</span>
      </button>
      <button
        type="button"
        className={`session-control-button ghost ds-focus-ring ${diagnosticsEnabled ? "active" : ""}`}
        onClick={onToggleDiagnostics || (() => {})}
        disabled={!isConnected || !onToggleDiagnostics}
      >
        <span className="session-control-icon">i</span>
        <span>{diagnosticsEnabled ? "Debug On" : "Debug"}</span>
      </button>
    </div>
  );
}
