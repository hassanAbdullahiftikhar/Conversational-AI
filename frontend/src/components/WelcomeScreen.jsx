import React from "react";
import "./WelcomeScreen.css";

const QUICK_PROMPTS = [
  {
    icon: "📦",
    title: "Track My Order",
    subtitle: "Get live status & delivery ETA",
    prompt: "I want to track my order.",
  },
  {
    icon: "↩️",
    title: "Returns & Refunds",
    subtitle: "Easy 14-day return process",
    prompt: "How do I return an item I received?",
  },
  {
    icon: "🛡️",
    title: "Warranty Claim",
    subtitle: "6–24 month product coverage",
    prompt: "My product stopped working. How do I file a warranty claim?",
  },
  {
    icon: "🚚",
    title: "Shipping Info",
    subtitle: "City-wise delivery & charges",
    prompt: "What are the delivery timelines and shipping charges to major cities?",
  },
];

export default function WelcomeScreen({ onQuickPrompt, isConnected }) {
  return (
    <div className="welcome-screen">
      <div className="welcome-orb welcome-orb-left" />
      <div className="welcome-orb welcome-orb-right" />

      <div className="welcome-hero-grid">
        <section className="welcome-story-panel">
          <div className="welcome-badge-row">
            <span className="welcome-chip ds-chip">Voice-first support</span>
            <span className={`welcome-chip ds-chip ${isConnected ? "online" : "offline"}`}>
              {isConnected ? "Live channel ready" : "Reconnecting"}
            </span>
          </div>

          <div className="hero-avatar">N</div>
          <p className="welcome-eyebrow ds-kicker">NexaKart support workspace</p>
          <h2 className="welcome-heading">Resolve orders, returns, and warranty questions in one conversational surface.</h2>
          <p className="welcome-subtitle">
            Nexa combines streaming responses, live voice capture, and voice playback controls so support feels immediate instead of transactional.
          </p>

          <div className="category-pills">
            <span className="pill">Electronics</span>
            <span className="pill">Headphones</span>
            <span className="pill">Peripherals</span>
            <span className="pill">Accessories</span>
          </div>

          <div className="welcome-metrics">
            <div className="metric-card">
              <span className="metric-value">24/7</span>
              <span className="metric-label">Conversational coverage</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">Text + Voice</span>
              <span className="metric-label">Unified support channel</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">Secure</span>
              <span className="metric-label">Session-scoped workflow</span>
            </div>
          </div>
        </section>

        <section className="quick-prompt-section">
          <div className="quick-prompt-header">
            <p className="section-label">Suggested starting points</p>
            <p className="section-subtitle">Jump into the most common customer support flows without typing a full prompt.</p>
          </div>
          <div className="quick-prompt-grid">
            {QUICK_PROMPTS.map((item) => (
              <button
                key={item.title}
                type="button"
                className="quick-prompt-card"
                onClick={() => onQuickPrompt(item.prompt)}
                disabled={!isConnected}
              >
                <span className="card-icon">{item.icon}</span>
                <div className="card-body">
                  <span className="card-title">{item.title}</span>
                  <span className="card-subtitle">{item.subtitle}</span>
                </div>
                <span className="card-arrow">→</span>
              </button>
            ))}
          </div>
        </section>
      </div>
      <div className="welcome-footer-strip">
        <span className="ds-chip">Streaming replies</span>
        <span className="ds-chip">Live speech transcription</span>
        <span className="ds-chip">Adjustable TTS playback</span>
        <span className="ds-chip">Session reset controls</span>
      </div>
    </div>
  );
}
