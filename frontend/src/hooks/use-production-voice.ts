'use client';

import { useRef, useState, useCallback, useEffect } from 'react';
import { getToken } from '@/lib/api';

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunk = 8192;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

const MULAW_DECODE_TABLE = new Int16Array(256);
(() => {
  for (let i = 0; i < 256; i++) {
    let sample = i ^ 0xFF;
    const sign = (sample & 0x80) !== 0;
    const exponent = (sample >> 4) & 0x07;
    const mantissa = sample & 0x0F;
    let value = ((mantissa << 3) + 0x84) << exponent;
    value -= 0x84;
    MULAW_DECODE_TABLE[i] = sign ? -value : value;
  }
})();

function mulawDecode(data: Uint8Array): Uint8Array {
  const pcm16 = new Uint8Array(data.length * 2);
  const view = new DataView(pcm16.buffer);
  for (let i = 0; i < data.length; i++) {
    view.setInt16(i * 2, MULAW_DECODE_TABLE[data[i]], true);
  }
  return pcm16;
}

interface UseProductionVoiceOptions {
  agentId: number | null;
  onTranscript?: (text: string) => void;
  onError?: (text: string) => void;
}

interface AudioFormat {
  encoding: string;
  sample_rate: number;
}

export function useProductionVoice(options: UseProductionVoiceOptions) {
  const { agentId, onTranscript, onError } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fatalErrorRef = useRef(false);

  // Refs for callbacks to avoid stale closures in WS handlers
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [audioFormat, setAudioFormat] = useState<AudioFormat | null>(null);
  const [ttsProvider, setTtsProvider] = useState<string | null>(null);
  const [ttsVoice, setTtsVoice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const audioFormatRef = useRef<AudioFormat | null>(null);
  const currentSourceRef = useRef<AudioBufferSourceNode | null>(null);

  const connect = useCallback(() => {
    if (!agentId) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    setConnecting(true);
    setError(null);
    fatalErrorRef.current = false;

    const token = getToken();
    if (!token) {
      setError('Not authenticated');
      setConnecting(false);
      return;
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000';
    const wsUrl = apiUrl.replace(/^http/, 'ws');
    const ws = new WebSocket(`${wsUrl}/api/playground/ws/${agentId}/voice`, ['bearer', token]);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0;
      setConnected(true);
      setConnecting(false);
      setError(null);
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch {
        // ignore
      }
    };

    ws.onerror = () => {
      setConnecting(false);
    };

    ws.onclose = () => {
      setConnected(false);
      setConnecting(false);
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      if (!fatalErrorRef.current && reconnectAttemptsRef.current < 5) {
        const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 16000);
        reconnectAttemptsRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => connect(), delay);
      }
    };
  }, [agentId]);

  const handleMessage = useCallback((data: Record<string, unknown>) => {
    const type = data.type as string;

    switch (type) {
      case 'voice_ready':
        setAudioFormat(data.audio_format as AudioFormat);
        audioFormatRef.current = data.audio_format as AudioFormat;
        setTtsProvider(data.tts_provider as string);
        setTtsVoice(data.tts_voice as string);
        break;

      case 'audio': {
        const audioB64 = data.data as string;
        if (audioB64) {
          const fmt = (data.format as AudioFormat | undefined) || audioFormatRef.current || undefined;
          playAudio(audioB64, fmt);
        }
        setSynthesizing(false);
        break;
      }

      case 'transcript': {
        const text = data.text as string;
        if (text) {
          onTranscriptRef.current?.(text);
        }
        setTranscribing(false);
        break;
      }

      case 'error':
        setError(data.text as string);
        setSynthesizing(false);
        setTranscribing(false);
        if (data.fatal) {
          fatalErrorRef.current = true;
        }
        onErrorRef.current?.(data.text as string);
        break;

      case 'pong':
        break;
    }
  }, []);

  const playAudio = useCallback(async (audioB64: string, format?: AudioFormat) => {
    try {
      const audioBytes = Uint8Array.from(atob(audioB64), (c) => c.charCodeAt(0));

      // Use Web Audio API to play raw PCM audio
      if (!audioContextRef.current) {
        audioContextRef.current = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      }
      const ctx = audioContextRef.current;
      if (ctx.state === 'suspended') {
        await ctx.resume();
      }
      // Stop any currently playing audio before starting new playback
      if (currentSourceRef.current) {
        try { currentSourceRef.current.stop(); } catch { /* already ended */ }
        currentSourceRef.current = null;
      }
      const sampleRate = format?.sample_rate || 16000;
      const encoding = format?.encoding || 'linear16';

      if (encoding === 'mulaw') {
        // MULAW is 8-bit, 1 byte per sample — decode to 16-bit PCM
        const pcm16 = mulawDecode(audioBytes);
        const audioBuffer = ctx.createBuffer(1, pcm16.length / 2, sampleRate);
        const channelData = audioBuffer.getChannelData(0);
        const view = new DataView(pcm16.buffer);
        for (let i = 0; i < channelData.length; i++) {
          const sample = view.getInt16(i * 2, true);
          channelData[i] = sample / 32768;
        }
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        currentSourceRef.current = source;
        source.start(0);
      } else {
        // linear16: 16-bit PCM, 2 bytes per sample
        const audioBuffer = ctx.createBuffer(1, audioBytes.length / 2, sampleRate);
        const channelData = audioBuffer.getChannelData(0);
        const view = new DataView(audioBytes.buffer);
        for (let i = 0; i < channelData.length; i++) {
          const sample = view.getInt16(i * 2, true);
          channelData[i] = sample / 32768;
        }
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        currentSourceRef.current = source;
        source.start(0);
      }
    } catch (e) {
      console.error('Failed to play audio:', e);
    }
  }, []);

  const stopAudio = useCallback(() => {
    if (currentSourceRef.current) {
      try { currentSourceRef.current.stop(); } catch { /* already ended */ }
      currentSourceRef.current = null;
    }
  }, []);

  const synthesize = useCallback((text: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      setSynthesizing(true);
      setError(null);
      wsRef.current.send(JSON.stringify({ type: 'synthesize', text }));
    }
  }, []);

  const transcribe = useCallback((audioData: ArrayBuffer, sampleRate: number = 16000) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      setTranscribing(true);
      setError(null);
      const b64 = arrayBufferToBase64(audioData);
      wsRef.current.send(JSON.stringify({
        type: 'transcribe',
        audio: b64,
        sample_rate: sampleRate,
        encoding: 'linear16',
      }));
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    reconnectAttemptsRef.current = 99;
    if (wsRef.current) {
      wsRef.current.close(1000, 'Manual disconnect');
      wsRef.current = null;
    }
    setConnected(false);
    setConnecting(false);
  }, []);

  // Cleanup
  useEffect(() => {
    return () => {
      reconnectAttemptsRef.current = 99; // prevent zombie auto-reconnect
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (wsRef.current) wsRef.current.close(1000, 'Component unmount');
      if (audioContextRef.current) {
        audioContextRef.current.close();
        audioContextRef.current = null;
      }
    };
  }, []);

  // Auto-connect
  useEffect(() => {
    if (agentId) {
      connect();
    } else {
      disconnect();
    }
    return () => {
      reconnectAttemptsRef.current = 99; // prevent zombie reconnect from old WS onclose
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (wsRef.current) {
        wsRef.current.close(1000, 'Agent changed');
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  return {
    connected,
    connecting,
    synthesizing,
    transcribing,
    audioFormat,
    ttsProvider,
    ttsVoice,
    error,
    connect,
    disconnect,
    synthesize,
    transcribe,
    stopAudio,
  };
}
