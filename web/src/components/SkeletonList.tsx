import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export interface SkeletonListProps {
  /** How many 56px rows to show (UI-SPEC: lists show 3). */
  rows?: number;
  /** Add a title bar above the rows, for page-level loading (a skeleton H1 plus the list). */
  withTitle?: boolean;
  className?: string;
}

/**
 * The loading state for a list or a whole page (D-47): a shimmering block per row at the member-row
 * height, so the page does not jump when the data arrives. The shimmer is the `Skeleton` sweep,
 * a static `bg-muted` block under prefers-reduced-motion. The blocks are decorative and hidden
 * from assistive technology; the region itself carries `aria-busy`.
 */
export function SkeletonList({
  rows = 3,
  withTitle = false,
  className,
}: SkeletonListProps) {
  return (
    <div aria-busy="true" className={cn('flex flex-col gap-4', className)}>
      {withTitle && <Skeleton className="h-8 w-2/3" />}
      {Array.from({ length: rows }, (_, index) => (
        // The rows are identical placeholders and never reorder.
        // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder rows
        <Skeleton key={index} className="h-14 w-full" />
      ))}
    </div>
  );
}
