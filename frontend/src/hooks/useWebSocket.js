import { useEffect, useRef, useState } from "react";

function buildWebSocketUrl(sessionId, token) {
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  const base = `${wsProtocol}://${window.location.host}/ws/chat/${sessionId}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export function useWebSocket({ sessionId, sessionToken, onToken, onDone, onError }) {
  const wsRef = useRef(null);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!sessionId || sessionToken === null) {
      return undefined;
    }

    const ws = new WebSocket(buildWebSocketUrl(sessionId, sessionToken));
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);
    ws.onerror = () => onError("Connection error");
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "token") {
          onToken(data.content || "");
        } else if (data.type === "done") {
          onDone();
        } else if (data.type === "error") {
          onError(data.content || "Unknown error");
        }
      } catch (_e) {
        onError("Invalid server message");
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
      setIsConnected(false);
    };
  }, [sessionId, sessionToken, onToken, onDone, onError]);

  const sendMessage = (content) => {
    const ws = wsRef.current;
    if (!ws) {
      onError("WebSocket is not connected");
      return;
    }
    if (ws.readyState === WebSocket.CONNECTING) {
      // Still handshaking. App gates sends on isConnected, so this is a safety net — drop silently.
      return;
    }
    if (ws.readyState !== WebSocket.OPEN) {
      onError("WebSocket is not connected");
      return;
    }
    ws.send(JSON.stringify({ type: "user_message", content }));
  };

  return { sendMessage, isConnected };
}
