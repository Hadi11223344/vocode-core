'use client';

import { useRef, useState, useCallback, useEffect } from 'react';

// ── Web Speech API type declarations (not in default TS lib) ───────────
interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionEvent {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  length: number;
  [index: number]: { transcript: string; confidence: number };
}

interface SpeechRecognitionErrorEvent {
  error: string;
  message: string;
}

interface UseVoiceChatOptions {
  onTranscript: (text: string) => void;
  onListeningChange?: (isListening: boolean) => void;
  preferredVoiceName?: string;
  preferredLanguage?: string;
}

export function useVoiceChat(options: UseVoiceChatOptions) {
  const { onTranscript, onListeningChange, preferredVoiceName, preferredLanguage } = options;
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(true);
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);

  // Refs for callbacks to avoid stale closures and unstable deps
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const onListeningChangeRef = useRef(onListeningChange);
  onListeningChangeRef.current = onListeningChange;

  useEffect(() => {
    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) {
      setIsSupported(false);
    }

    const loadVoices = () => {
      const voices = window.speechSynthesis.getVoices();
      setAvailableVoices(voices);
    };
    loadVoices();
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }

    return () => {
      if (window.speechSynthesis.onvoiceschanged !== undefined) {
        window.speechSynthesis.onvoiceschanged = null;
      }
      window.speechSynthesis.cancel();
    };
  }, []);

  const startListening = useCallback(() => {
    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) return;

    // Cancel any ongoing speech before listening
    window.speechSynthesis.cancel();

    const rec = new SpeechRecognitionAPI();
    rec.continuous = false;
    rec.interimResults = true;
    rec.lang = preferredLanguage || 'en-US';
    rec.maxAlternatives = 1;

    rec.onresult = (event: SpeechRecognitionEvent) => {
      const latestResult = event.results[event.results.length - 1];
      if (!latestResult || !latestResult.isFinal) {
        return;
      }

      const transcript = latestResult[0]?.transcript?.trim();
      if (transcript) {
        onTranscriptRef.current(transcript);
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'no-speech') {
        // Ignore no-speech errors — user may have released early
        return;
      }
      if (event.error === 'aborted') {
        // Expected when we stop listening intentionally
        return;
      }
      console.warn('Speech recognition error:', event.error);
    };

    rec.onend = () => {
      setIsListening(false);
      onListeningChangeRef.current?.(false);
      // If we got a final transcript before ending, it's already handled in onresult
    };

    rec.start();
    recognitionRef.current = rec;
    setIsListening(true);
    onListeningChangeRef.current?.(true);
  }, []);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // Already stopped
      }
      recognitionRef.current = null;
    }
    setIsListening(false);
    onListeningChangeRef.current?.(false);
  }, []);

  const toggleListening = useCallback(() => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  }, [isListening, startListening, stopListening]);

  const speak = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
      utterance.lang = preferredLanguage || 'en-US';

      // Prefer a natural-sounding voice
      const voices = availableVoices.length > 0 ? availableVoices : window.speechSynthesis.getVoices();
      const preferred =
        (preferredVoiceName
          ? voices.find((v) => v.name === preferredVoiceName)
          : null) ||
        (preferredLanguage
          ? voices.find((v) => v.lang === preferredLanguage)
            || voices.find((v) => v.lang.startsWith(preferredLanguage.split('-')[0]))
          : null) ||
        voices.find((v) => v.name.includes('Google')) ||
        voices.find((v) => v.name.includes('Samantha')) ||
        voices.find((v) => v.lang.startsWith('en'));
      if (preferred) utterance.voice = preferred;

      window.speechSynthesis.speak(utterance);
    },
    [availableVoices, preferredLanguage, preferredVoiceName]
  );

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis.cancel();
  }, []);

  return {
    isListening,
    isSupported,
    startListening,
    stopListening,
    toggleListening,
    speak,
    stopSpeaking,
    availableVoices,
  };
}
