import type { CSSProperties } from 'react';

interface Particle {
  top: string;
  left: string;
  dx: string;
  dy: string;
  delay: string;
  duration: string;
  tone: 'volt' | 'cyan' | 'uv';
}

const PARTICLES: Particle[] = [
  { top: '6%', left: '14%', dx: '24px', dy: '160px', delay: '-2s', duration: '26s', tone: 'volt' },
  { top: '22%', left: '82%', dx: '-30px', dy: '200px', delay: '-11s', duration: '34s', tone: 'cyan' },
  { top: '48%', left: '6%', dx: '36px', dy: '180px', delay: '-7s', duration: '30s', tone: 'uv' },
  { top: '66%', left: '74%', dx: '-22px', dy: '220px', delay: '-19s', duration: '38s', tone: 'volt' },
  { top: '82%', left: '38%', dx: '18px', dy: '140px', delay: '-4s', duration: '28s', tone: 'cyan' },
  { top: '92%', left: '90%', dx: '-26px', dy: '120px', delay: '-15s', duration: '32s', tone: 'uv' },
];

/**
 * The single ambient layer shared by the entire landing journey: technical
 * grid, chapter-reactive light, drifting particles and a signal rail.
 * Decorative, non-interactive, and paused by the page-level visibility hook.
 */
export function LandingEnvironment() {
  return (
    <div className="zq-env" aria-hidden="true">
      <div className="zq-env-grid zq-env-anim" />

      <div className="zq-env-glow zq-env-glow--uv zq-env-anim" />
      <div className="zq-env-glow zq-env-glow--cyan zq-env-anim" />
      <div className="zq-env-glow zq-env-glow--volt zq-env-anim" />

      <div className="zq-env-particles">
        {PARTICLES.map((particle, index) => (
          <span
            key={index}
            className={`zq-env-particle zq-env-particle--${particle.tone} zq-env-anim`}
            style={
              {
                top: particle.top,
                left: particle.left,
                '--zq-drift-x': particle.dx,
                '--zq-drift-y': particle.dy,
                '--zq-drift-delay': particle.delay,
                '--zq-drift-duration': particle.duration,
              } as CSSProperties
            }
          />
        ))}
      </div>

      <div className="zq-env-rail">
        <span className="zq-env-rail-line" />
        <span className="zq-env-rail-node" style={{ top: '16%' }} />
        <span className="zq-env-rail-node" style={{ top: '42%' }} />
        <span className="zq-env-rail-node" style={{ top: '68%' }} />
        <span className="zq-env-rail-node" style={{ top: '92%' }} />
        <span className="zq-env-rail-pulse zq-env-anim" />
      </div>
    </div>
  );
}
