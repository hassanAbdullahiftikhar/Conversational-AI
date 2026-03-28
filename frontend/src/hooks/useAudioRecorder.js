import { useCallback, useRef, useState } from "react";

const TARGET_SAMPLE_RATE = 16000;
const CHUNK_DURATION_MS = 250;
const PROCESSOR_BUFFER_SIZE = 4096;

function downsampleBuffer(inputBuffer, inputSampleRate, outputSampleRate) {
  if (inputSampleRate === outputSampleRate) {
    return new Float32Array(inputBuffer);
  }

  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.round(inputBuffer.length / ratio);
  const result = new Float32Array(outputLength);
  let outputIndex = 0;
  let inputIndex = 0;

  while (outputIndex < outputLength) {
    const nextInputIndex = Math.round((outputIndex + 1) * ratio);
    let total = 0;
    let count = 0;
    for (let index = inputIndex; index < nextInputIndex && index < inputBuffer.length; index += 1) {
      total += inputBuffer[index];
      count += 1;
    }
    result[outputIndex] = count > 0 ? total / count : 0;
    outputIndex += 1;
    inputIndex = nextInputIndex;
  }

  return result;
}

function float32ToInt16(floatBuffer) {
  const int16Buffer = new Int16Array(floatBuffer.length);
  for (let index = 0; index < floatBuffer.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, floatBuffer[index]));
    int16Buffer[index] = sample < 0 ? sample * 32768 : sample * 32767;
  }
  return int16Buffer;
}

export function useAudioRecorder({
  sendControlMessage,
  sendBinaryMessage,
  onPermissionDenied,
  onRecordingStart,
  onRecordingStop,
}) {
  const [isRecording, setIsRecording] = useState(false);

  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const sourceRef = useRef(null);
  const gainRef = useRef(null);
  const streamRef = useRef(null);
  const pendingSamplesRef = useRef([]);

  const cleanup = useCallback(async () => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current.onaudioprocess = null;
      processorRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (gainRef.current) {
      gainRef.current.disconnect();
      gainRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      await audioContextRef.current.close();
      audioContextRef.current = null;
    }
    pendingSamplesRef.current = [];
  }, []);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioContextImpl = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioContextImpl({ sampleRate: TARGET_SAMPLE_RATE });
      audioContextRef.current = audioContext;
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(PROCESSOR_BUFFER_SIZE, 1, 1);
      const gainNode = audioContext.createGain();
      gainNode.gain.value = 0;

      sourceRef.current = source;
      processorRef.current = processor;
      gainRef.current = gainNode;

      const samplesPerChunk = Math.floor(
        (TARGET_SAMPLE_RATE * CHUNK_DURATION_MS) / 1000
      );
      pendingSamplesRef.current = [];

      processor.onaudioprocess = (event) => {
        const channelData = event.inputBuffer.getChannelData(0);
        const downsampled = downsampleBuffer(
          channelData,
          audioContext.sampleRate,
          TARGET_SAMPLE_RATE
        );
        const pendingSamples = pendingSamplesRef.current;

        for (let index = 0; index < downsampled.length; index += 1) {
          pendingSamples.push(downsampled[index]);
        }

        while (pendingSamples.length >= samplesPerChunk) {
          const chunk = pendingSamples.splice(0, samplesPerChunk);
          const int16Chunk = float32ToInt16(Float32Array.from(chunk));
          sendBinaryMessage(int16Chunk.buffer.slice(0));
        }
      };

      source.connect(processor);
      processor.connect(gainNode);
      gainNode.connect(audioContext.destination);

      sendControlMessage(JSON.stringify({ type: "audio_start" }));
      onRecordingStart?.();
      setIsRecording(true);
    } catch (err) {
      await cleanup();
      setIsRecording(false);
      if (err?.name === "NotAllowedError" || err?.name === "PermissionDeniedError") {
        onPermissionDenied?.("Microphone permission denied. Please allow microphone access and try again.");
      } else if (err?.name === "NotFoundError") {
        onPermissionDenied?.("No microphone found. Please connect a microphone and try again.");
      } else if (err?.name === "NotReadableError") {
        onPermissionDenied?.("Microphone is in use by another application.");
      } else {
        onPermissionDenied?.("Unable to access microphone. Please check your audio settings.");
      }
    }
  }, [cleanup, onPermissionDenied, onRecordingStart, sendBinaryMessage, sendControlMessage]);

  const stopRecording = useCallback(async () => {
    if (!isRecording) {
      return;
    }

    const pendingSamples = pendingSamplesRef.current;
    if (pendingSamples.length > 0) {
      const int16Chunk = float32ToInt16(Float32Array.from(pendingSamples));
      sendBinaryMessage(int16Chunk.buffer.slice(0));
    }

    sendControlMessage(JSON.stringify({ type: "audio_end" }));
    setIsRecording(false);
    onRecordingStop?.();
    await cleanup();
  }, [cleanup, isRecording, onRecordingStop, sendBinaryMessage, sendControlMessage]);

  return { isRecording, startRecording, stopRecording };
}
