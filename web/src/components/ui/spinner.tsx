import { Loader2Icon } from 'lucide-react';
import type * as React from 'react';
import { cn } from '@/lib/utils';

/*
 * shadcn/ui spinner (radix-nova registry item, MIT), made decorative: no `role="status"`, so the
 * sandbox banner stays the only status region on a page (AppShell.test.tsx). The pending button
 * announces itself with `aria-busy` instead (UI-SPEC "Interaction and Motion").
 */
function Spinner({ className, ...props }: React.ComponentProps<'svg'>) {
  return (
    <Loader2Icon
      data-slot="spinner"
      aria-hidden="true"
      className={cn('size-5 animate-spin', className)}
      {...props}
    />
  );
}

export { Spinner };
