"use client";

import { useCallback, useState } from "react";

/**
 * Reusable hook to prevent double form submissions.
 *
 * Usage:
 *   const { isSubmitting, handleSubmit } = useFormSubmit(async (e) => {
 *     await createAgent(data);
 *   });
 *
 *   <form onSubmit={handleSubmit}>
 *     <button disabled={isSubmitting}>
 *       {isSubmitting ? "Saving..." : "Save"}
 *     </button>
 *   </form>
 */
export function useFormSubmit<T extends (...args: any[]) => Promise<any>>(
  onSubmit: T
) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = useCallback(
    async (...args: Parameters<T>) => {
      if (isSubmitting) return; // ignore duplicate clicks
      setIsSubmitting(true);
      try {
        await onSubmit(...args);
      } finally {
        setIsSubmitting(false);
      }
    },
    [onSubmit, isSubmitting]
  );

  return { isSubmitting, handleSubmit };
}
