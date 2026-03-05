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
      <div className="welcome-hero">
        <div className="hero-avatar">N</div>
        <h2 className="welcome-heading">Hi, I&apos;m Nexa</h2>
        <p className="welcome-subtitle">
          NexaKart&apos;s AI support assistant — here to help with your orders,
          returns, warranty claims, and more. Available 24/7.
        </p>
        <div className="category-pills">
          <span className="pill">📱 Electronics</span>
          <span className="pill">🎧 Headphones</span>
          <span className="pill">⌨️ Peripherals</span>
          <span className="pill">🔋 Accessories</span>
        </div>
      </div>

      <div className="quick-prompt-section">
        <p className="section-label">Quick actions — tap to get started</p>
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
      </div>
    </div>
  );
}
