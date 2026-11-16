import type { CSSProperties, ReactNode } from 'react';
import { useRef } from 'react';
import { usePointerGlow } from '../hooks/usePointerGlow';
import { cn } from '../../../lib/utils';

interface SpotlightProps {
  children: ReactNode;
  className?: string;
}

/** Wraps a surface with a restrained pointer-tracked illumination. */
export function Spotlight({ children, className }: SpotlightProps) {
  const ref = useRef<HTMLDivElement>(null);
  usePointerGlow(ref);

  return (
    <div ref={ref} className={cn('zq-spotlight', className)}>
      {children}
    </div>
  );
}

interface SignalDot {
  top: string;
  left: string;
  dx: string;
  dy: string;
  delay: string;
  duration: string;
  tone: 'volt' | 'cyan' | 'uv';
}

const SIGNALS: SignalDot[] = [
  { top: '22%', left: '6%', dx: '340px', dy: '110px', delay: '-2s', duration: '19s', tone: 'volt' },
  { top: '68%', left: '14%', dx: '260px', dy: '-90px', delay: '-9s', duration: '23s', tone: 'cyan' },
  { top: '34%', left: '44%', dx: '250px', dy: '150px', delay: '-14s', duration: '26s', tone: 'uv' },
  { top: '78%', left: '58%', dx: '210px', dy: '-130px', delay: '-5s', duration: '21s', tone: 'volt' },
  { top: '16%', left: '72%', dx: '-170px', dy: '170px', delay: '-17s', duration: '29s', tone: 'cyan' },
  { top: '52%', left: '82%', dx: '-220px', dy: '-100px', delay: '-11s', duration: '24s', tone: 'volt' },
];

/**
 * Decorative hero environment: technical grid, ambient light, signal arcs,
 * travelling points and coordinate labels. Entirely aria-hidden and static
 * under prefers-reduced-motion.
 */
export function HeroAmbience() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="zq-parallax absolute -inset-24" data-depth="1">
        <div className="zq-hero-grid zq-ambient-anim h-full w-full" />
      </div>

      <div className="zq-parallax absolute inset-0" data-depth="2">
        <div className="zq-hero-glow zq-hero-glow--violet zq-ambient-anim" />
        <div className="zq-hero-glow zq-hero-glow--cyan zq-hero-glow--slow zq-ambient-anim" />
        <div className="zq-hero-glow zq-hero-glow--volt zq-hero-glow--slower zq-ambient-anim" />
      </div>

      <div className="zq-parallax absolute inset-0" data-depth="3">
        <svg
          className="zq-hero-arcs h-full w-full"
          viewBox="0 0 1200 700"
          fill="none"
          preserveAspectRatio="xMidYMid slice"
        >
          <path
            className="zq-arc zq-arc--volt"
            d="M-80 540 C 180 430, 340 640, 610 470 S 980 260, 1280 380"
          />
          <path
            className="zq-arc zq-arc--cyan"
            d="M-60 240 C 240 150, 430 330, 700 210 S 1020 90, 1260 190"
          />
          <path
            className="zq-arc zq-arc--uv"
            d="M120 760 C 260 520, 520 560, 640 380 S 760 120, 1020 -20"
          />
          <circle cx="610" cy="470" r="2.5" fill="rgba(200,255,61,0.55)" />
          <circle cx="700" cy="210" r="2" fill="rgba(34,211,238,0.5)" />
          <circle cx="640" cy="380" r="2" fill="rgba(139,92,246,0.6)" />
        </svg>
      </div>

      <div className="absolute inset-0">
        {SIGNALS.map((signal, index) => (
          <span
            key={index}
            className={`zq-signal zq-signal--${signal.tone}`}
            style={
              {
                top: signal.top,
                left: signal.left,
                '--zq-dx': signal.dx,
                '--zq-dy': signal.dy,
                '--zq-delay': signal.delay,
                '--zq-duration': signal.duration,
              } as CSSProperties
            }
          />
        ))}

        <span className="zq-coord" style={{ top: '12%', left: '4%' }}>
          X 041.20 / Y 118.70
        </span>
        <span className="zq-coord" style={{ top: '46%', left: '48%' }}>
          ZQ-CORE // SIGNAL
        </span>
        <span className="zq-coord" style={{ bottom: '14%', right: '6%' }}>
          GRID 56 · SYNC 0.98
        </span>
      </div>
    </div>
  );
}
