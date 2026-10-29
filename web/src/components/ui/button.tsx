import { cva, type VariantProps } from 'class-variance-authority';
import { Slot } from 'radix-ui';
import type * as React from 'react';
import { cn } from '@/lib/utils';

/*
 * shadcn/ui button (radix-nova registry item, MIT), restyled to 01-UI-SPEC.md: 44px high on every
 * breakpoint (D-46), 8px radius, 16px semibold label, token colours only, light mode only.
 * Variants: default (coral, the single primary action per screen), outline, secondary, ghost,
 * destructive and link.
 */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-transparent text-base font-semibold whitespace-nowrap transition-colors duration-150 ease-out outline-none select-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 aria-busy:cursor-progress [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-5",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary-hover',
        outline:
          'border-input bg-background text-foreground hover:bg-accent aria-expanded:bg-accent',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-accent aria-expanded:bg-accent',
        ghost: 'text-foreground hover:bg-accent aria-expanded:bg-accent',
        destructive:
          'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        link: 'text-foreground underline underline-offset-4 hover:bg-accent',
      },
      size: {
        default: 'h-11 min-w-11 px-4',
        icon: 'size-11',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

function Button({
  className,
  variant = 'default',
  size = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : 'button';

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
