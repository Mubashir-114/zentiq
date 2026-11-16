import { useEffect, type RefObject } from 'react';

/**
 * Marks the page with the id of the chapter currently crossing the reading
 * line. A single passive scroll listener plus one rAF read per frame; the host
 * gets a data attribute and CSS handles the lighting transition, so scrolling
 * never re-renders React.
 */
export function useChapterAmbience(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const host = ref.current;
    if (!host) return;

    const chapters = Array.from(host.querySelectorAll<HTMLElement>('[data-chapter]'));
    if (chapters.length === 0) return;

    let frame = 0;

    const resolve = () => {
      frame = 0;
      const viewport = window.innerHeight;
      let active = host.dataset.chapter ?? chapters[0].dataset.chapter ?? 'hero';
      let largest = 0;

      for (const chapter of chapters) {
        const rect = chapter.getBoundingClientRect();
        const visible = Math.min(rect.bottom, viewport) - Math.max(rect.top, 0);
        if (visible > largest) {
          largest = visible;
          active = chapter.dataset.chapter ?? active;
        }
      }

      // Whichever chapter dominates the viewport lights the environment. The
      // design chapter still wins at the very bottom of the page, where a
      // reading line could never reach it.
      if (largest > 0) host.dataset.chapter = active;
    };

    const schedule = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(resolve);
    };

    resolve();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);

    return () => {
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [ref]);
}
