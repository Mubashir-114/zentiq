import { UPCOMING_MODULES } from '../constants/upcomingModules';
import { Card } from '../../../components/ui/Card';
import { Badge } from '../../../components/ui/Badge';

export function UpcomingModulesGrid() {
  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
      role="list"
      aria-label="Planned platform modules"
    >
      {UPCOMING_MODULES.map((module) => {
        const Icon = module.icon;
        return (
          <Card
            key={module.id}
            role="listitem"
            className="p-5 flex flex-col justify-between border-white/10 bg-[#1B1E2D]/70 space-y-3"
          >
            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="w-9 h-9 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-[#22D3EE]">
                  <Icon className="w-4 h-4" aria-hidden="true" />
                </div>
                <Badge variant="neutral" className="text-[10px]">
                  Coming soon
                </Badge>
              </div>

              <div>
                <h3 className="text-sm font-semibold text-[#F4F4F8] tracking-tight">
                  {module.title}
                </h3>
                <p className="mt-1 text-xs text-[#9298AD] leading-relaxed line-clamp-3">
                  {module.description}
                </p>
              </div>
            </div>

            <div className="pt-2.5 border-t border-white/5 text-[11px] text-[#9298AD]/80 font-mono">
              {module.provisionalMilestone}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

