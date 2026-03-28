import { useEffect, useRef, useState } from "react";

function buildWebSocketUrl(sessionId, token) {
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  const base = `${wsProtocol}://${window.location.host}/ws/chat/${sessionId}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export function useWebSocket({
  sessionId,
  sessionToken,
  onToken,
  onDone,
  onError,
  onAudioChunk,
  onAsrPartial,
  onAsrFinal,
}) {
  const wsRef = useRef(null);
  const pendingAudioResponseIdRef = useRef(null);
  const [isConnected, setIsConnected] = useState(false);

  // Store callbacks in a ref so WebSocket reconnection only depends on
  // sessionId / sessionToken — not on callback identity.
  const callbacksRef = useRef({ onToken, onDone, onError, onAudioChunk, onAsrPartial, onAsrFinal });
  useEffect(() => {
    callbacksRef.current = { onToken, onDone, onError, onAudioChunk, onAsrPartial, onAsrFinal };
  });

  useEffect(() => {
    if (!sessionId || sessionToken === null) {
      return undefined;
    }

    const ws = new WebSocket(buildWebSocketUrl(sessionId, sessionToken));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);
    ws.onerror = () => callbacksRef.current.onError("Connection error");
    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        callbacksRef.current.onAudioChunk?.(
          new Uint8Array(event.data),
          pendingAudioResponseIdRef.current
        );
        pendingAudioResponseIdRef.current = null;
        return;
      }
      try {
        const data = JSON.parse(event.data);
        if (data.type === "token") {
          callbacksRef.current.onToken(data.content || "", data.response_id || null);
        } else if (data.type === "done") {
          callbacksRef.current.onDone(data.response_id || null);
        } else if (data.type === "error") {
          callbacksRef.current.onError(data.content || "Unknown error");
        } else if (data.type === "asr_partial") {
          callbacksRef.current.onAsrPartial?.(data.content || data.text || "");
        } else if (data.type === "asr_final") {
          callbacksRef.current.onAsrFinal?.(data.content || data.text || "");
        } else if (data.type === "audio_segment") {
          pendingAudioResponseIdRef.current = data.response_id || null;
        } else if (data.type === "voice_preferences_set") {
        }
      } catch (_e) {
        callbacksRef.current.onError("Invalid server message");
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
      setIsConnected(false);
    };
  }, [sessionId, sessionToken]);

  const sendMessage = (content) => {
    const ws = wsRef.current;
    if (!ws) {
      callbacksRef.current.onError("WebSocket is not connected");
      return;
    }
    if (ws.readyState === WebSocket.CONNECTING) {
      return;
    }
    if (ws.readyState !== WebSocket.OPEN) {
      callbacksRef.current.onError("WebSocket is not connected");
      return;
    }

    ws.send(JSON.stringify({ type: "user_message", content }));
  };

  const sendRaw = (jsonString) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(jsonString);
    }
  };

  const sendBinary = (arrayBuffer) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(arrayBuffer);
    }
  };

  return { sendMessage, sendRaw, sendBinary, isConnected };
}
