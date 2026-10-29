import { cva, type VariantProps } from 'class-variance-authority';
import { Slot } from 'radix-ui';
import type * as React from 'react';
import { cn } from '@/lib/utils';

/*
 * shadcn/ui badge (radix-nova registry item, MIT), restyled to 01-UI-SPEC.md: 14px semibold Label
 * role, 8px radius, neutral by default (`Organiser`, `Demo persona`), never coral. The `money`
 * variant is for the `PayPal saved` status only (money blue is reserved for money moments).
 */
const badgeVariants = cva(
  'inline-flex min-h-6 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-lg border px-2 text-sm font-semibold leading-[1.4] whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:size-4',
  {
    variants: {
      variant: {
        default: 'border-border bg-muted text-foreground',
        outline: 'border-border bg-background text-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        destructive: 'border-destructive bg-background text-destructive',
        money: 'border-money bg-money-surface text-money',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

function Badge({
  className,
  variant = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'span';

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
