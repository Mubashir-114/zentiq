import React, { forwardRef } from 'react';
import { cn } from '../../lib/utils';
import { Loader2 } from 'lucide-react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'cyan' | 'secondary' | 'outline' | 'ghost' | 'destructive';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      children,
      variant = 'primary',
      size = 'md',
      isLoading = false,
      disabled,
      leftIcon,
      rightIcon,
      ...props
    },
    ref
  ) => {
    const baseStyles =
      'zq-focus-ring inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-control font-medium tracking-[-0.01em] transition-[background-color,border-color,color,box-shadow,transform] duration-[var(--duration-base)] ease-[var(--ease-out-expo)] focus:outline-none active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 disabled:active:translate-y-0';

    const variants = {
      primary: 'zq-glow-volt bg-volt text-void hover:bg-volt-dim',
      cyan: 'bg-cyan text-void hover:bg-cyan-dim',
      secondary:
        'border border-hairline bg-panel-elevated text-ink hover:border-hairline-strong hover:bg-panel',
      outline:
        'border border-hairline bg-transparent text-ink hover:border-volt/45 hover:bg-volt/5 hover:text-volt-soft',
      ghost: 'bg-transparent text-ink-muted hover:bg-white/[0.04] hover:text-ink',
      destructive:
        'border border-danger/40 bg-danger/10 text-danger hover:border-danger/60 hover:bg-danger/20',
    };

    const sizes = {
      sm: 'h-8 px-3 text-xs',
      md: 'h-10 px-4 text-sm',
      lg: 'h-12 px-6 text-base',
    };

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        {...props}
      >
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          leftIcon
        )}
        <span>{children}</span>
        {!isLoading && rightIcon}
      </button>
    );
  }
);

Button.displayName = 'Button';
