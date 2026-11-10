import React, { forwardRef } from 'react';
import { cn } from '../../lib/utils';
import { Loader2 } from 'lucide-react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'cyan' | 'secondary' | 'outline' | 'ghost';
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
      'inline-flex items-center justify-center font-medium rounded-lg transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[#10121E] disabled:opacity-50 disabled:cursor-not-allowed select-none active:scale-[0.98]';

    const variants = {
      primary:
        'bg-[#8B5CF6] hover:bg-[#7C3AED] text-white shadow-sm shadow-[#8B5CF6]/20 focus-visible:ring-[#8B5CF6]',
      cyan:
        'bg-[#22D3EE] hover:bg-[#06B6D4] text-[#10121E] font-semibold shadow-sm shadow-[#22D3EE]/20 focus-visible:ring-[#22D3EE]',
      secondary:
        'bg-[#1B1E2D] hover:bg-[#262A3E] text-[#F4F4F8] border border-white/10 focus-visible:ring-white/20',
      outline:
        'bg-transparent hover:bg-white/5 text-[#F4F4F8] border border-white/20 hover:border-white/40 focus-visible:ring-white/20',
      ghost:
        'bg-transparent hover:bg-white/5 text-[#9298AD] hover:text-[#F4F4F8] focus-visible:ring-white/20',
    };

    const sizes = {
      sm: 'text-xs px-3 py-1.5 gap-1.5',
      md: 'text-sm px-4 py-2 gap-2',
      lg: 'text-base px-6 py-3 gap-2.5',
    };

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        {...props}
      >
        {isLoading ? (
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
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

