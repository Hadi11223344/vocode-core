'use client';

import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'voia_onboarding_v1';

export interface OnboardingState {
  started: boolean;
  completed: boolean;
  currentStep: number;
  agentId: number | null;
  kbId: number | null;
  dismissedAt: string | null;
}

const DEFAULT_STATE: OnboardingState = {
  started: false,
  completed: false,
  currentStep: 0,
  agentId: null,
  kbId: null,
  dismissedAt: null,
};

function loadState(): OnboardingState {
  if (typeof window === 'undefined') return DEFAULT_STATE;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULT_STATE, ...JSON.parse(raw) };
  } catch {
    // ignore
  }
  return DEFAULT_STATE;
}

function saveState(state: OnboardingState) {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function useOnboarding() {
  const [state, setState] = useState<OnboardingState>(DEFAULT_STATE);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setState(loadState());
    setHydrated(true);
  }, []);

  const update = useCallback((patch: Partial<OnboardingState>) => {
    setState((prev) => {
      const next = { ...prev, ...patch };
      saveState(next);
      return next;
    });
  }, []);

  const start = useCallback(() => {
    update({ started: true, completed: false, currentStep: 0, dismissedAt: null });
  }, [update]);

  const goToStep = useCallback((step: number) => {
    update({ currentStep: step });
  }, [update]);

  const nextStep = useCallback(() => {
    setState((prev) => {
      const next = { ...prev, currentStep: prev.currentStep + 1 };
      saveState(next);
      return next;
    });
  }, []);

  const prevStep = useCallback(() => {
    setState((prev) => {
      const next = { ...prev, currentStep: Math.max(0, prev.currentStep - 1) };
      saveState(next);
      return next;
    });
  }, []);

  const complete = useCallback(() => {
    update({ completed: true, started: false, currentStep: 0 });
  }, [update]);

  const dismiss = useCallback(() => {
    update({ dismissedAt: new Date().toISOString() });
  }, [update]);

  const reset = useCallback(() => {
    saveState(DEFAULT_STATE);
    setState(DEFAULT_STATE);
  }, []);

  const isResumable =
    state.started &&
    !state.completed &&
    state.currentStep > 0 &&
    state.currentStep < 5;

  return {
    state,
    hydrated,
    start,
    goToStep,
    nextStep,
    prevStep,
    complete,
    dismiss,
    reset,
    isResumable,
    update,
  };
}
