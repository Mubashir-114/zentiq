import React from 'react';
import { cn } from '../../lib/utils';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  glow?: boolean;
  featured?: boolean;
}

export function Card({ className, glow = false, featured = false, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'zq-surface-highlight relative isolate overflow-hidden rounded-card border border-hairline bg-panel shadow-panel transition-[border-color,box-shadow,transform] duration-[var(--duration-base)] ease-[var(--ease-out-expo)]',
        featured && 'bg-panel-elevated',
        glow && 'hover:-translate-y-0.5 hover:border-volt/30 hover:shadow-elevated',
        className
      )}
      {...props}
    >
      {featured && (
        <>
          <div
            className="zq-ambient pointer-events-none absolute inset-0 -z-10 opacity-60"
            aria-hidden="true"
          />
          <div
            className="zq-grid-bg pointer-events-none absolute inset-0 -z-10 opacity-[0.05]"
            aria-hidden="true"
          />
          <div
            className="zq-signal-line pointer-events-none absolute inset-x-6 top-0 h-px"
            aria-hidden="true"
          />
          <div
            className="zq-corners pointer-events-none absolute inset-0"
            aria-hidden="true"
          />
        </>
      )}
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('flex flex-col gap-1.5 p-6 pb-3', className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn('font-display text-heading font-semibold text-ink', className)}
      {...props}
    >
      {children}
    </h3>
  );
}

export function CardDescription({ className, children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn('text-sm leading-relaxed text-ink-muted', className)} {...props}>
      {children}
    </p>
  );
}

export function CardContent({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('p-6 pt-3', className)} {...props}>
      {children}
    </div>
  );
}

export function CardFooter({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('zq-hairline mt-4 flex items-center border-t px-6 py-4', className)}
      {...props}
    >
      {children}
    </div>
  );
}
