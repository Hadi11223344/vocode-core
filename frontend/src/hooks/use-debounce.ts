'use client';

import { useState, useEffect } from 'react';

/**
 * Debounce a value by a specified delay.
 * FE-07: API debounce on all search inputs (300ms)
 */
export function useDebounce<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
