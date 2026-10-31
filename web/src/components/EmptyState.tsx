import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface EmptyStateProps {
  /** The friendly heading, for example `Just you so far. Send the invite!` (UI-SPEC locked copy). */
  title: string;
  /** The line under the heading. */
  description?: string;
  /** The heading level, so a page keeps its outline (one H1, then H2 sections, then H3). */
  as?: 'h2' | 'h3';
  /** An optional call to action, such as the `Start a trip` button. */
  action?: ReactNode;
  className?: string;
}

/**
 * A friendly empty state (D-47, D-42): warm and plain, text only. The copy is passed in so each
 * screen uses its own locked UI-SPEC strings; this component owns the look and the heading level.
 */
export function EmptyState({
  title,
  description,
  as: Heading = 'h2',
  action,
  className,
}: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <Heading
        className={cn(
          'text-balance break-words font-semibold',
          Heading === 'h2' ? 'text-xl leading-[1.2]' : 'text-base',
        )}
      >
        {title}
      </Heading>
      {description !== undefined && (
        <p className="text-muted-foreground">{description}</p>
      )}
      {action !== undefined && <div className="mt-2">{action}</div>}
    </div>
  );
}
