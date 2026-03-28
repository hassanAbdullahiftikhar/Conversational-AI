import React from "react";
import "./VoiceSelector.css";

const VOICES = [
  { id: "af_bella", label: "Bella" },
  { id: "af_sarah", label: "Sarah" },
  { id: "af_nicole", label: "Nicole" },
  { id: "am_michael", label: "Michael" },
];

const SPEED_OPTIONS = [
  0.25,
  0.5,
  0.75,
  1.0,
  1.25,
  1.5,
  1.75,
  2.0,
  2.25,
  2.5,
  2.75,
  3.0,
].map((value) => ({ value, label: `${value}x` }));

/**
 * VoiceSelector — horizontal row of pill buttons for TTS voice selection.
 */
export default function VoiceSelector({
  currentVoice,
  currentSpeed,
  speechEnabled,
  onVoiceChange,
  onSpeedChange,
  onSpeechToggle,
  disabled,
}) {
  return (
    <div className="voice-panel">
      <div className="voice-panel-group">
        <span className="voice-panel-label">Voice</span>
        {VOICES.map((v) => {
          const isActive = v.id === currentVoice;
          return (
            <button
              key={v.id}
              type="button"
              className={`voice-chip ${isActive ? "active" : ""}`}
              onClick={() => onVoiceChange(v.id)}
              disabled={disabled}
              aria-pressed={isActive}
              title={`Voice: ${v.label}`}
            >
              {v.label}
            </button>
          );
        })}
      </div>

      <div className="voice-panel-group">
        <span className="voice-panel-label">Speed</span>
        <select
          value={String(currentSpeed)}
          onChange={(event) => onSpeedChange(Number(event.target.value))}
          disabled={disabled}
          className="voice-speed-select"
          aria-label="Voice speed"
          title="Voice speed"
        >
          {SPEED_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="voice-panel-group">
        <span className="voice-panel-label">Speech</span>
        <button
          type="button"
          className={`voice-toggle ${speechEnabled ? "active" : ""}`}
          onClick={onSpeechToggle}
          disabled={disabled}
          aria-pressed={speechEnabled}
          title={speechEnabled ? "Disable voice playback" : "Enable voice playback"}
        >
          {speechEnabled ? "Voice On" : "Voice Off"}
        </button>
      </div>
    </div>
  );
}
