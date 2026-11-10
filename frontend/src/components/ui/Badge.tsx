import React from 'react';
import { cn } from '../../lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'success' | 'warning' | 'error' | 'cyan' | 'violet' | 'gold' | 'neutral';
  dot?: boolean;
}

export function Badge({
  className,
  variant = 'neutral',
  dot = false,
  children,
  ...props
}: BadgeProps) {
  const variants = {
    success: 'bg-[#34D399]/15 text-[#34D399] border-[#34D399]/30',
    warning: 'bg-[#FBBF24]/15 text-[#FBBF24] border-[#FBBF24]/30',
    error: 'bg-[#FB7185]/15 text-[#FB7185] border-[#FB7185]/30',
    cyan: 'bg-[#22D3EE]/15 text-[#22D3EE] border-[#22D3EE]/30',
    violet: 'bg-[#8B5CF6]/15 text-[#A78BFA] border-[#8B5CF6]/30',
    gold: 'bg-[#F5C451]/15 text-[#F5C451] border-[#F5C451]/30',
    neutral: 'bg-white/10 text-[#9298AD] border-white/10',
  };

  const dotColors = {
    success: 'bg-[#34D399]',
    warning: 'bg-[#FBBF24]',
    error: 'bg-[#FB7185]',
    cyan: 'bg-[#22D3EE]',
    violet: 'bg-[#8B5CF6]',
    gold: 'bg-[#F5C451]',
    neutral: 'bg-[#9298AD]',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border',
        variants[variant],
        className
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn('w-1.5 h-1.5 rounded-full animate-pulse', dotColors[variant])}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}

