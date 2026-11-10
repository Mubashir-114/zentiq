import type { SkillDomain } from '../types';
import { Badge } from '../../../components/ui/Badge';
import { Card } from '../../../components/ui/Card';

interface SkillDomainCardProps {
  domain: SkillDomain;
}

export function SkillDomainCard({ domain }: SkillDomainCardProps) {
  const Icon = domain.icon;

  const categoryColorVariants: Record<string, 'cyan' | 'violet' | 'gold' | 'neutral'> = {
    Cognitive: 'violet',
    Analytical: 'cyan',
    Perceptual: 'violet',
    Technical: 'cyan',
    Applied: 'gold',
  };

  const badgeVariant = categoryColorVariants[domain.category] || 'neutral';

  return (
    <Card
      glow
      className="p-5 flex flex-col justify-between border-white/10 hover:border-white/20 transition-all space-y-4"
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="w-10 h-10 rounded-lg bg-[#8B5CF6]/10 border border-[#8B5CF6]/20 flex items-center justify-center text-[#8B5CF6]">
            <Icon className="w-5 h-5" aria-hidden="true" />
          </div>
          <Badge variant={badgeVariant} className="text-[10px]">
            {domain.category}
          </Badge>
        </div>

        <div>
          <h3 className="text-base font-semibold text-[#F4F4F8] tracking-tight">
            {domain.name}
          </h3>
          <p className="mt-1 text-xs text-[#9298AD] leading-relaxed line-clamp-3">
            {domain.description}
          </p>
        </div>
      </div>

      <div className="pt-3 border-t border-white/5 flex items-center justify-between text-xs">
        <span className="text-[11px] text-[#9298AD]">
          Diagnostics coming soon
        </span>
        <Badge variant="neutral" dot>
          Not Assessed
        </Badge>
      </div>
    </Card>
  );
}

