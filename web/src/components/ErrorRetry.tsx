import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface ErrorRetryProps {
  /** Try the failed load again. */
  onRetry: () => void;
  /** The heading level: a whole-page failure is the page's H1, a failure in one section an H2. */
  as?: 'h1' | 'h2';
  className?: string;
}

/**
 * A plain-language load error with a way out (D-47): what happened, what to do, and a `Retry
 * loading` button. The copy is the UI-SPEC "Error state (load)" row. The sandbox banner, header
 * and tab bar stay on screen around it because only the page content is swapped.
 */
export function ErrorRetry({
  onRetry,
  as: Heading = 'h1',
  className,
}: ErrorRetryProps) {
  return (
    <div className={cn('flex flex-col items-start gap-2', className)}>
      <Heading className="text-xl font-semibold leading-[1.2]">
        We couldn't load that.
      </Heading>
      <p className="text-muted-foreground">
        Check your connection and try again.
      </p>
      <Button type="button" onClick={onRetry} className="mt-2">
        Retry loading
      </Button>
    </div>
  );
}
