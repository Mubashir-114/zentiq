import { useEffect, type RefObject } from 'react';

/**
 * Pauses ambient animations when the document is hidden or the host scrolls
 * out of view. Toggles one data attribute; there is no per-frame work.
 */
export function useAmbientPause(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    let hidden = document.visibilityState === 'hidden';
    let inView = true;

    const apply = () => {
      element.dataset.ambient = hidden || !inView ? 'paused' : 'active';
    };

    const handleVisibility = () => {
      hidden = document.visibilityState === 'hidden';
      apply();
    };

    document.addEventListener('visibilitychange', handleVisibility);

    let observer: IntersectionObserver | null = null;
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(
        ([entry]) => {
          inView = entry.isIntersecting;
          apply();
        },
        { threshold: 0.05 }
      );
      observer.observe(element);
    }

    apply();

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      observer?.disconnect();
    };
  }, [ref]);
}
