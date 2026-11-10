import { SKILL_DOMAINS } from '../constants/skillDomains';
import { SkillDomainCard } from './SkillDomainCard';

export function SkillDomainGrid() {
  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 gap-4"
      role="list"
      aria-label="Cognitive skill domains"
    >
      {SKILL_DOMAINS.map((domain) => (
        <div key={domain.id} role="listitem">
          <SkillDomainCard domain={domain} />
        </div>
      ))}
    </div>
  );
}

