import { useEffect } from 'react';

/**
 * Set the document title for the current page.
 * Automatically appends " · VOIA" as a suffix.
 */
export function usePageTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · VOIA`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
