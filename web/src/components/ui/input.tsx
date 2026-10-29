import type * as React from 'react';
import { cn } from '@/lib/utils';

/*
 * shadcn/ui input (radix-nova registry item, MIT), restyled to 01-UI-SPEC.md: 44px high, 16px
 * text on every breakpoint (no iOS zoom on focus), 8px radius, `--input` border (3:1 non-text).
 */
function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'h-11 w-full min-w-0 rounded-lg border border-input bg-background px-4 text-base text-foreground transition-colors duration-150 ease-out outline-none file:inline-flex file:h-9 file:border-0 file:bg-transparent file:text-sm file:font-semibold file:text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive',
        className,
      )}
      {...props}
    />
  );
}

export { Input };
