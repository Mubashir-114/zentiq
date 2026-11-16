import type { CSSProperties } from 'react';

interface OrbitTag {
  label: string;
  tone: 'uv' | 'volt' | 'cyan';
  delay: string;
  phase: 'a' | 'b' | 'c';
}

const ORBIT_TAGS: OrbitTag[] = [
  { label: 'LEARN', tone: 'uv', delay: '0s', phase: 'a' },
  { label: 'CHALLENGE', tone: 'volt', delay: '-14.66s', phase: 'b' },
  { label: 'EVOLVE', tone: 'cyan', delay: '-29.33s', phase: 'c' },
];

/**
 * The hero's ecosystem visual: a core with three orbiting stages and a slow
 * activity pulse. Purely decorative — the same three stages are exposed as real
 * content in the learning-protocol list below.
 */
export function EcosystemCore() {
  return (
    <div className="eco-core zq-parallax" data-depth="4" aria-hidden="true">
      <div className="eco-core__halo" />

      <div className="eco-core__ring eco-core__ring--outer zq-ambient-anim" />
      <div className="eco-core__ring eco-core__ring--mid zq-ambient-anim" />
      <div className="eco-core__ring eco-core__ring--inner" />

      {ORBIT_TAGS.map((tag) => (
        <div
          key={tag.label}
          className={`eco-core__orbit eco-core__orbit--${tag.phase} zq-ambient-anim`}
          style={{ animationDelay: tag.delay }}
        >
          <span
            className={`eco-core__tag eco-core__tag--${tag.tone}`}
            style={{ animationDelay: tag.delay } as CSSProperties}
          >
            {tag.label}
          </span>
        </div>
      ))}

      <div className="eco-core__center">
        <div className="eco-core__hex" />
        <span className="eco-core__glyph">Z</span>
        <span className="eco-core__pulse" />
      </div>

      <div className="eco-core__readout">
        <span>3-STAGE LOOP</span>
        <span className="eco-core__readout-dot" />
        <span>ACTIVE</span>
      </div>
    </div>
  );
}
