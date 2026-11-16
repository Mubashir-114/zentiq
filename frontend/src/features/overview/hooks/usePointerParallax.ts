import { useEffect, type RefObject } from 'react';

/**
 * Writes normalized pointer coordinates to CSS custom properties on the host.
 * One rAF write per frame, no React state, disabled for coarse pointers and
 * users who request reduced motion.
 */
export function usePointerParallax(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const coarsePointer = window.matchMedia('(pointer: coarse)');
    if (reducedMotion.matches || coarsePointer.matches) return;

    let frame = 0;
    let x = 0;
    let y = 0;

    const commit = () => {
      frame = 0;
      element.style.setProperty('--zq-px', x.toFixed(4));
      element.style.setProperty('--zq-py', y.toFixed(4));
    };

    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(commit);
    };

    const handleMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      x = (event.clientX - rect.left) / rect.width - 0.5;
      y = (event.clientY - rect.top) / rect.height - 0.5;
      schedule();
    };

    const handleLeave = () => {
      x = 0;
      y = 0;
      schedule();
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
