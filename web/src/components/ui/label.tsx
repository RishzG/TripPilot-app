import { Label as LabelPrimitive } from 'radix-ui';
import type * as React from 'react';
import { cn } from '@/lib/utils';

/* shadcn/ui label (radix-nova registry item, MIT), restyled to the 14px semibold Label role. */
function Label({
  className,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        'flex items-center gap-2 text-sm font-semibold leading-[1.4] select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}

export { Label };
