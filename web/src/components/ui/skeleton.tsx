import type * as React from 'react';
import { cn } from '@/lib/utils';

/*
 * shadcn/ui skeleton (radix-nova registry item, MIT), restyled to D-47: `bg-muted` base with a
 * 1.5s linear sweep from `--muted` to `--accent` and back. Under reduced motion it is a static
 * `bg-muted` block. Decorative: `aria-hidden`; the loading region carries `aria-busy`.
 */
function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn(
        'animate-shimmer rounded-lg bg-muted bg-[linear-gradient(90deg,var(--muted)_0%,var(--accent)_50%,var(--muted)_100%)] bg-[length:200%_100%] motion-reduce:animate-none motion-reduce:bg-none',
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
