import React from 'react';
import type { LucideIcon } from 'lucide-react';

interface DashboardSectionHeaderProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  badge?: React.ReactNode;
}

export function DashboardSectionHeader({
  title,
  description,
  icon: Icon,
  badge,
}: DashboardSectionHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-2 border-b border-white/5">
      <div className="space-y-0.5">
        <div className="flex items-center gap-2.5">
          {Icon && <Icon className="w-5 h-5 text-[#8B5CF6]" aria-hidden="true" />}
          <h2 className="text-lg sm:text-xl font-bold tracking-tight text-[#F4F4F8]">
            {title}
          </h2>
        </div>
        {description && (
          <p className="text-xs sm:text-sm text-[#9298AD]">
            {description}
          </p>
        )}
      </div>
      {badge && <div className="shrink-0">{badge}</div>}
    </div>
  );
}

