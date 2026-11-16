import { useEffect, type RefObject } from 'react';

/**
 * Tracks the pointer inside a surface and exposes it as --zq-mx / --zq-my
 * percentages for a CSS radial highlight. No React state; rAF-throttled.
 */
export function usePointerGlow(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (window.matchMedia('(pointer: coarse)').matches) return;

    let frame = 0;
    let mx = 50;
    let my = 50;

    const commit = () => {
      frame = 0;
      element.style.setProperty('--zq-mx', `${mx.toFixed(1)}%`);
      element.style.setProperty('--zq-my', `${my.toFixed(1)}%`);
      // Restrained tilt: max ±2.2° / ±2.6° at the edges of the surface.
      element.style.setProperty('--zq-rx', `${(((my - 50) / 50) * -2.2).toFixed(2)}deg`);
      element.style.setProperty('--zq-ry', `${(((mx - 50) / 50) * 2.6).toFixed(2)}deg`);
    };

    const handleMove = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      mx = ((event.clientX - rect.left) / rect.width) * 100;
      my = ((event.clientY - rect.top) / rect.height) * 100;
      if (!frame) frame = window.requestAnimationFrame(commit);
    };

    const handleLeave = () => {
      mx = 50;
      my = 50;
      if (!frame) frame = window.requestAnimationFrame(commit);
    };

    element.addEventListener('pointermove', handleMove, { passive: true });
    element.addEventListener('pointerleave', handleLeave, { passive: true });

    return () => {
      element.removeEventListener('pointermove', handleMove);
      element.removeEventListener('pointerleave', handleLeave);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [ref]);
}
