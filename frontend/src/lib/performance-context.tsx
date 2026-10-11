'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';

type Quality = 'high' | 'low' | 'off';

interface PerformanceContextValue {
  quality: Quality;
  setQuality: (q: Quality) => void;
  toggleEnabled: () => void;
  autoDetected: boolean;
}

const PerformanceContext = createContext<PerformanceContextValue>({
  quality: 'high',
  setQuality: () => {},
  toggleEnabled: () => {},
  autoDetected: false,
});

export function usePerformance() {
  return useContext(PerformanceContext);
}

function detectQuality(): Quality {
  if (typeof window === 'undefined') return 'high';

  // Respect reduced motion
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    return 'off';
  }

  const cores = navigator.hardwareConcurrency || 4;

  // Quick canvas benchmark — try WebGL2 first (preferred on Apple Metal)
  try {
    const canvas = document.createElement('canvas');
    const gl =
      canvas.getContext('webgl2', { powerPreference: 'high-performance' }) ||
      canvas.getContext('webgl', { powerPreference: 'high-performance' }) ||
      canvas.getContext('experimental-webgl', { powerPreference: 'high-performance' }) as WebGLRenderingContext | null;
    if (!gl) return 'off';

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : '';
    const isSoftware = /swiftshader|llvmpipe|software/i.test(renderer);

    if (isSoftware) return 'off';

    // Apple Silicon (M1/M2/M3+) — always high performance with Metal
    if (/Apple (M\d|GPU|Metal)/i.test(renderer)) return 'high';

    // Only downgrade for genuinely low-core devices
    if (cores <= 2) return 'low';

    return 'high';
  } catch {
    return 'low';
  }
}

const STORAGE_KEY = 'voia-perf-quality';

export function PerformanceProvider({ children }: { children: React.ReactNode }) {
  const [quality, setQualityState] = useState<Quality>('high');
  const [autoDetected, setAutoDetected] = useState(false);

  useEffect(() => {
    // Check stored preference first
    const stored = localStorage.getItem(STORAGE_KEY) as Quality | null;
    if (stored && ['high', 'low', 'off'].includes(stored)) {
      setQualityState(stored);
      setAutoDetected(false);
    } else {
      const detected = detectQuality();
      setQualityState(detected);
      setAutoDetected(true);
      localStorage.setItem(STORAGE_KEY, detected);
    }
  }, []);

  const setQuality = useCallback((q: Quality) => {
    setQualityState(q);
    setAutoDetected(false);
    localStorage.setItem(STORAGE_KEY, q);
  }, []);

  const toggleEnabled = useCallback(() => {
    setQualityState((prev) => {
      const next: Quality = prev === 'off' ? 'high' : 'off';
      localStorage.setItem(STORAGE_KEY, next);
      return next;
    });
  }, []);

  return (
    <PerformanceContext.Provider value={{ quality, setQuality, toggleEnabled, autoDetected }}>
      {children}
    </PerformanceContext.Provider>
  );
}
