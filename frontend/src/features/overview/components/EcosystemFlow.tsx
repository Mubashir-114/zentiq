import { Fragment, type CSSProperties } from 'react';

interface Stage {
  index: string;
  label: string;
  tone: 'uv' | 'volt' | 'cyan';
  copy: string;
}

const STAGES: Stage[] = [
  {
    index: '01',
    label: 'Learn',
    tone: 'uv',
    copy: 'Build the mental model behind each cognitive domain.',
  },
  {
    index: '02',
    label: 'Challenge',
    tone: 'volt',
    copy: 'Apply it under the published assessment conditions.',
  },
  {
    index: '03',
    label: 'Evolve',
    tone: 'cyan',
    copy: 'Turn every evaluated attempt into durable mastery.',
  },
];

/**
 * LEARN → CHALLENGE → EVOLVE signal pipeline. Real list content (not an image),
 * with a controlled active-stage cycle and animated signal connectors.
 */
export function EcosystemFlow() {
  return (
    <ol className="eco-flow list-none" aria-label="The ZENTIQ learning protocol">
      {STAGES.map((stage, index) => (
        <Fragment key={stage.index}>
          <li
            className={`eco-stage eco-stage--${stage.tone}`}
            style={{ '--stage-delay': `${index * 3}s` } as CSSProperties}
          >
            <div className="eco-stage__top">
              <span className="eco-stage__index">{stage.index}</span>
              <span className="eco-stage__dot" aria-hidden="true" />
            </div>
            <h3>{stage.label}</h3>
            <p>{stage.copy}</p>
          </li>

          {index < STAGES.length - 1 && (
            <li className="eco-flow__link" aria-hidden="true">
              <span className="eco-flow__signal" />
            </li>
          )}
        </Fragment>
      ))}
    </ol>
  );
}
