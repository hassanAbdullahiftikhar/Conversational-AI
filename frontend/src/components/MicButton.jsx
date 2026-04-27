import React, { useEffect } from "react";
import "./MicButton.css";

/**
 * MicButton — circular microphone button with recording/processing states.
 *
 * States:
 *   idle       : teal mic icon
 *   recording  : red pulsing circle
 *   processing : spinner animation
 */
export default function MicButton({ isRecording, isProcessing, onClick, disabled }) {
  const micSvg = (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke={isRecording ? "#dc2626" : "#0f6f79"}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="9" y="1" width="6" height="12" rx="3" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );

  return (
    <button
      type="button"
      className={`mic-button ds-focus-ring${isRecording ? " recording" : ""}${isProcessing ? " processing" : ""}`}
      onClick={onClick}
      disabled={disabled}
      aria-label={isRecording ? "Stop recording" : isProcessing ? "Processing voice" : "Start recording"}
      title={isRecording ? "Stop recording" : "Voice input"}
    >
      {isRecording ? <span className="mic-button-ring" /> : null}
      {isProcessing ? <span className="mic-button-spinner" /> : micSvg}
    </button>
  );
}
