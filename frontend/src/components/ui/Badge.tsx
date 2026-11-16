import React from 'react';
import { cn } from '../../lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'volt' | 'success' | 'warning' | 'error' | 'cyan' | 'violet' | 'gold' | 'neutral';
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
    volt: 'border-volt/35 bg-volt/10 text-volt-soft',
    success: 'border-success/30 bg-success/10 text-success',
    warning: 'border-warning/30 bg-warning/10 text-warning',
    error: 'border-danger/30 bg-danger/10 text-danger',
    cyan: 'border-cyan/30 bg-cyan/10 text-cyan',
    violet: 'border-ultraviolet/35 bg-ultraviolet/10 text-ultraviolet-soft',
    gold: 'border-gold/30 bg-gold/10 text-gold',
    neutral: 'border-hairline bg-white/[0.03] text-ink-muted',
  };

  const dotColors = {
    volt: 'bg-volt',
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-danger',
    cyan: 'bg-cyan',
    violet: 'bg-ultraviolet',
    gold: 'bg-gold',
    neutral: 'bg-ink-muted',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-[0.08em]',
        variants[variant],
        className
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn('h-1.5 w-1.5 rounded-full animate-pulse', dotColors[variant])}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
