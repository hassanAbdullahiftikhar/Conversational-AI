import { useCallback, useRef, useState } from "react";

/**
 * useAudioPlayer — queues and plays WAV audio chunks in order.
 *
 * AudioContext is created lazily on first enqueueChunk call
 * (browser autoplay policy compliance — must be inside user gesture chain).
 */
export function useAudioPlayer() {
  const [isPlaying, setIsPlaying] = useState(false);
  const audioCtxRef = useRef(null);
  const queueRef = useRef([]);
  const playingRef = useRef(false);
  const mutedResponsesRef = useRef(new Set());
  const sourceRef = useRef(null);
  const currentResponseIdRef = useRef(null);
  const playbackGenerationRef = useRef(0);

  const _getOrCreateContext = () => {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtxRef.current.state === "suspended") {
      audioCtxRef.current.resume().catch(() => {});
    }
    return audioCtxRef.current;
  };

  const _playNext = useCallback(() => {
    if (queueRef.current.length === 0) {
      playingRef.current = false;
      setIsPlaying(false);
      return;
    }

    playingRef.current = true;
    setIsPlaying(true);

    const chunk = queueRef.current.shift();
    const generationAtSchedule = playbackGenerationRef.current;
    currentResponseIdRef.current = chunk.responseId;
    const ctx = _getOrCreateContext();

    // Clone the ArrayBuffer to avoid detached buffer issues
    const buffer = chunk.uint8Array.buffer.slice(
      chunk.uint8Array.byteOffset,
      chunk.uint8Array.byteOffset + chunk.uint8Array.byteLength
    );

    ctx.decodeAudioData(
      buffer,
      (audioBuffer) => {
        if (generationAtSchedule !== playbackGenerationRef.current) {
          return;
        }

        if (mutedResponsesRef.current.has(chunk.responseId)) {
          currentResponseIdRef.current = null;
          _playNext();
          return;
        }

        const source = ctx.createBufferSource();
        sourceRef.current = source;
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        source.onended = () => {
          if (sourceRef.current === source) {
            sourceRef.current = null;
          }
          if (generationAtSchedule !== playbackGenerationRef.current) {
            return;
          }
          currentResponseIdRef.current = null;
          _playNext();
        };
        source.start();
      },
      (_err) => {
        if (generationAtSchedule !== playbackGenerationRef.current) {
          return;
        }
        // Skip undecodable chunk and move to next
        currentResponseIdRef.current = null;
        _playNext();
      }
    );
  }, []);

  const enqueueChunk = useCallback(
    (uint8Array, responseId) => {
      if (!responseId || mutedResponsesRef.current.has(responseId)) {
        return;
      }
      _getOrCreateContext(); // Ensure context exists (user gesture chain)
      queueRef.current.push({ responseId, uint8Array });
      if (!playingRef.current) {
        _playNext();
      }
    },
    [_playNext]
  );

  const stop = useCallback(() => {
    playbackGenerationRef.current += 1;
    queueRef.current = [];
    playingRef.current = false;
    setIsPlaying(false);
    currentResponseIdRef.current = null;
    if (sourceRef.current) {
      try {
        sourceRef.current.stop();
      } catch (_err) {
      }
      sourceRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.suspend();
    }
  }, []);

  const muteResponse = useCallback((responseId) => {
    if (!responseId) {
      return;
    }
    mutedResponsesRef.current.add(responseId);
    queueRef.current = queueRef.current.filter((item) => item.responseId !== responseId);
    if (currentResponseIdRef.current === responseId && sourceRef.current) {
      try {
        sourceRef.current.stop();
      } catch (_err) {
      }
    }
  }, []);

  const unmuteResponse = useCallback((responseId) => {
    if (!responseId) {
      return;
    }
    mutedResponsesRef.current.delete(responseId);
  }, []);

  return { enqueueChunk, isPlaying, stop, muteResponse, unmuteResponse };
}
