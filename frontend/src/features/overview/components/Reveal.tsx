import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { cn } from '../../../lib/utils';

interface RevealProps {
  children: ReactNode;
  className?: string;
  /** Stagger in milliseconds, applied only to the CSS transition. */
  delay?: number;
  /** Direction the content travels from. Defaults to a short rise. */
  from?: 'up' | 'left' | 'right';
  /** Override the observer inset, e.g. for content pinned to the page bottom. */
  rootMargin?: string;
}

/**
 * Scroll reveal for landing sections. The effect writes a data attribute on the
 * host element — no React state, so no cascading renders. Content stays in the
 * accessibility tree; reduced-motion users get the final state immediately.
 */
export function Reveal({
  children,
  className,
  delay = 0,
  from = 'up',
  rootMargin = '0px 0px -6% 0px',
}: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const reveal = () => {
      element.dataset.reveal = 'visible';
    };

    if (
      window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      !('IntersectionObserver' in window)
    ) {
      reveal();
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        reveal();
        observer.disconnect();
      },
      { threshold: 0.12, rootMargin }
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [rootMargin]);

  return (
    <div
      ref={ref}
      className={cn('zq-reveal', className)}
      data-reveal="hidden"
      data-from={from}
      style={{ '--zq-reveal-delay': `${delay}ms` } as CSSProperties}
    >
      {children}
    </div>
  );
}
