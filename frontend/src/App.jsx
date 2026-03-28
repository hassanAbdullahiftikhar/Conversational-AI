import React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import ChatWindow from "./components/ChatWindow";
import MicButton from "./components/MicButton";
import SessionControls from "./components/SessionControls";
import VoiceSelector from "./components/VoiceSelector";
import WelcomeScreen from "./components/WelcomeScreen";
import { useAudioPlayer } from "./hooks/useAudioPlayer";
import { useAudioRecorder } from "./hooks/useAudioRecorder";
import { useWebSocket } from "./hooks/useWebSocket";
import "./App.css";

const API_BASE = "/api";
const VOICE_LABELS = {
  af_bella: "Bella",
  af_sarah: "Sarah",
  af_nicole: "Nicole",
  am_michael: "Michael",
};

export default function App() {
  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [sessionToken, setSessionToken] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [currentVoice, setCurrentVoice] = useState("af_bella");
  const [voiceSpeed, setVoiceSpeed] = useState(1.0);
  const [speechEnabled, setSpeechEnabled] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [partialTranscript, setPartialTranscript] = useState("");
  const [mutedResponseIds, setMutedResponseIds] = useState([]);
  const [renderedView, setRenderedView] = useState("welcome");
  const [viewPhase, setViewPhase] = useState("idle");
  const activeResponseIdRef = useRef(null);

  const {
    enqueueChunk,
    stop: stopAudioPlayback,
    muteResponse,
    unmuteResponse,
  } = useAudioPlayer();

  const onToken = useCallback((token, responseId) => {
    setPartialTranscript("");
    setIsProcessing(false);
    if (responseId && activeResponseIdRef.current !== responseId) {
      activeResponseIdRef.current = responseId;
      stopAudioPlayback();
    }
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === "assistant" && last.id === responseId) {
        const updated = [...prev];
        updated[updated.length - 1] = { ...last, content: `${last.content}${token}` };
        return updated;
      }
      return [...prev, { id: responseId || `assistant-${Date.now()}`, role: "assistant", content: token }];
    });
  }, [stopAudioPlayback]);

  const onDone = useCallback(() => {
    setIsStreaming(false);
    setIsProcessing(false);
    setPartialTranscript("");
  }, []);

  const onError = useCallback((errorText) => {
    setIsStreaming(false);
    setIsProcessing(false);
    setPartialTranscript("");
    setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${errorText}` }]);
  }, []);

  const onAudioChunk = useCallback(
    (uint8Array, responseId) => {
      if (!speechEnabled) {
        return;
      }
      enqueueChunk(uint8Array, responseId);
    },
    [enqueueChunk, speechEnabled]
  );

  const onAsrPartial = useCallback((transcript) => {
    setPartialTranscript(transcript);
  }, []);

  const onAsrFinal = useCallback((transcript) => {
    const finalTranscript = transcript.trim();
    setPartialTranscript("");
    if (!finalTranscript) {
      setIsProcessing(false);
      return;
    }
    stopAudioPlayback();
    activeResponseIdRef.current = null;
    setMessages((prev) => [...prev, { role: "user", content: finalTranscript }]);
    setIsStreaming(true);
  }, [stopAudioPlayback]);

  const { sendMessage, sendRaw, sendBinary, isConnected } = useWebSocket({
    sessionId,
    sessionToken,
    onToken,
    onDone,
    onError,
    onAudioChunk,
    onAsrPartial,
    onAsrFinal,
  });

  const handleMicPermissionDenied = useCallback((reason) => {
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: `⚠️ ${reason || "Microphone error. Please check your settings."}` },
    ]);
    setIsProcessing(false);
    setPartialTranscript("");
  }, []);

  const { isRecording, startRecording, stopRecording } = useAudioRecorder({
    sendControlMessage: sendRaw,
    sendBinaryMessage: sendBinary,
    onPermissionDenied: handleMicPermissionDenied,
    onRecordingStart: () => {
      setPartialTranscript("");
      setIsProcessing(false);
    },
    onRecordingStop: () => {
      setIsProcessing(true);
    },
  });

  const handleMicClick = useCallback(() => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  const handleVoiceChange = useCallback(
    (voice) => {
      setCurrentVoice(voice);
      sendRaw(
        JSON.stringify({
          type: "set_voice_preferences",
          voice,
          speed: voiceSpeed,
          speech_enabled: speechEnabled,
        })
      );
    },
    [sendRaw, speechEnabled, voiceSpeed]
  );

  const handleSpeedChange = useCallback(
    (speed) => {
      setVoiceSpeed(speed);
      sendRaw(
        JSON.stringify({
          type: "set_voice_preferences",
          voice: currentVoice,
          speed,
          speech_enabled: speechEnabled,
        })
      );
    },
    [currentVoice, sendRaw, speechEnabled]
  );

  const handleSpeechToggle = useCallback(() => {
    setSpeechEnabled((prev) => {
      const next = !prev;
      if (!next) {
        stopAudioPlayback();
      }
      sendRaw(
        JSON.stringify({
          type: "set_voice_preferences",
          voice: currentVoice,
          speed: voiceSpeed,
          speech_enabled: next,
        })
      );
      return next;
    });
  }, [currentVoice, sendRaw, stopAudioPlayback, voiceSpeed]);

  const isBusy = isStreaming || isRecording || isProcessing;

  const createSession = useCallback(async () => {
    const response = await fetch(`${API_BASE}/sessions`, { method: "POST" });
    const data = await response.json();
    setSessionId(data.session_id);
    setSessionToken(data.token || "");
  }, []);

  useEffect(() => {
    createSession().catch(() => {
      setMessages([{ role: "assistant", content: "Error: Unable to create session. Please refresh." }]);
    });
  }, [createSession]);

  const shouldShowWelcome = messages.length === 0 && !isRecording && !isProcessing && !partialTranscript;

  useEffect(() => {
    const targetView = shouldShowWelcome ? "welcome" : "chat";
    if (targetView === renderedView) {
      setViewPhase("idle");
      return undefined;
    }

    setViewPhase("exit");

    const swapTimer = window.setTimeout(() => {
      setRenderedView(targetView);
      setViewPhase("enter");
    }, 160);

    const settleTimer = window.setTimeout(() => {
      setViewPhase("idle");
    }, 520);

    return () => {
      window.clearTimeout(swapTimer);
      window.clearTimeout(settleTimer);
    };
  }, [shouldShowWelcome, renderedView]);

  const handleSend = useCallback(() => {
    const trimmed = inputValue.trim();
    if (!trimmed || isBusy || !isConnected) return;
    stopAudioPlayback();
    activeResponseIdRef.current = null;
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInputValue("");
    setIsStreaming(true);
    sendMessage(trimmed);
  }, [inputValue, isBusy, isConnected, sendMessage, stopAudioPlayback]);

  const handleQuickPrompt = useCallback((prompt) => {
    if (!isConnected || isBusy) {
      setInputValue(prompt);
      return;
    }
    stopAudioPlayback();
    activeResponseIdRef.current = null;
    setMessages((prev) => [...prev, { role: "user", content: prompt }]);
    setIsStreaming(true);
    sendMessage(prompt);
  }, [isBusy, isConnected, sendMessage, stopAudioPlayback]);

  const onNewSession = useCallback(async () => {
    try {
      if (sessionId) {
        await fetch(`${API_BASE}/sessions/${sessionId}?token=${encodeURIComponent(sessionToken)}`, { method: "DELETE" });
      }
      stopAudioPlayback();
      activeResponseIdRef.current = null;
      setMutedResponseIds([]);
      setMessages([]);
      setIsStreaming(false);
      setIsProcessing(false);
      setPartialTranscript("");
      await createSession();
    } catch {
      setMessages([{ role: "assistant", content: "Error: Unable to start a new session. Please refresh." }]);
      setIsStreaming(false);
    }
  }, [sessionId, sessionToken, createSession, stopAudioPlayback]);

  const onReset = useCallback(async () => {
    if (!sessionId) return;
    try {
      await fetch(`${API_BASE}/sessions/${sessionId}/reset?token=${encodeURIComponent(sessionToken)}`, { method: "POST" });
      stopAudioPlayback();
      activeResponseIdRef.current = null;
      setMutedResponseIds([]);
      setMessages([]);
      setIsStreaming(false);
      setIsProcessing(false);
      setPartialTranscript("");
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "Error: Unable to reset session." }]);
      setIsStreaming(false);
    }
  }, [sessionId, sessionToken, stopAudioPlayback]);

  const toggleMuteResponse = useCallback(
    (responseId) => {
      if (!responseId) {
        return;
      }
      setMutedResponseIds((prev) => {
        if (prev.includes(responseId)) {
          unmuteResponse(responseId);
          return prev.filter((id) => id !== responseId);
        }
        muteResponse(responseId);
        return [...prev, responseId];
      });
    },
    [muteResponse, unmuteResponse]
  );

  const onInputKeyDown = (event) => {
    if (event.key === "Enter") handleSend();
  };

  const currentVoiceLabel = VOICE_LABELS[currentVoice] || "Bella";
  const inputStatusText = !isConnected
    ? "Reconnecting to support services"
    : isRecording
      ? "Listening for your question"
      : isProcessing
        ? "Transcribing your voice"
        : isStreaming
          ? "Generating a support response"
          : "Ready for text or voice input";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-logo">N</div>
          <div className="brand-text">
            <span className="brand-name">NexaKart</span>
            <span className="brand-tagline">Voice-first customer support workspace</span>
          </div>
        </div>
        <div className="header-right">
          <div className={`status-badge ${isConnected ? "online" : "offline"}`}>
            <span className="status-dot" />
            {isConnected ? "Online" : "Connecting…"}
          </div>
          <VoiceSelector
            currentVoice={currentVoice}
            currentSpeed={voiceSpeed}
            speechEnabled={speechEnabled}
            onVoiceChange={handleVoiceChange}
            onSpeedChange={handleSpeedChange}
            onSpeechToggle={handleSpeechToggle}
            disabled={!isConnected || isBusy}
          />
          <SessionControls onNewSession={onNewSession} onReset={onReset} isConnected={isConnected} />
        </div>
      </header>

      <main className="content-stage ds-view-stage">
        <div className={`content-stage-shell ds-view-shell phase-${viewPhase} view-${renderedView}`}>
          {renderedView === "welcome" ? (
            <WelcomeScreen onQuickPrompt={handleQuickPrompt} isConnected={isConnected} />
          ) : (
            <ChatWindow
              messages={messages}
              isStreaming={isStreaming}
              partialTranscript={partialTranscript}
              mutedResponseIds={mutedResponseIds}
              onToggleMuteResponse={toggleMuteResponse}
            />
          )}
        </div>
      </main>

      <div className="input-area">
        <div className="input-shell">
          <div className="input-row">
            <input
              type="text"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="Ask about your order, returns, warranty, or shipping…"
              disabled={isBusy}
            />
            <div className="input-actions">
              <MicButton
                isRecording={isRecording}
                isProcessing={isProcessing}
                onClick={handleMicClick}
                disabled={!isConnected || (isBusy && !isRecording)}
              />
              <button
                type="button"
                className="send-btn"
                onClick={handleSend}
                disabled={isBusy || !inputValue.trim() || !isConnected}
              >
                Send
              </button>
            </div>
          </div>
          <div className="input-meta">
            <span className={`input-status-pill ${isBusy ? "busy" : "idle"}`}>{inputStatusText}</span>
            <span className="input-meta-copy">
              {speechEnabled
                ? `Voice reply set to ${currentVoiceLabel} at ${voiceSpeed}x.`
                : "Voice playback is currently off."}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
