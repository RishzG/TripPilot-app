import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock, PanelRightClose, PanelRightOpen } from 'lucide-react';
import {
  type FormEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import { ErrorRetry } from '@/components/ErrorRetry';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ApiError, api, unwrap } from '@/lib/api';
import { cn } from '@/lib/utils';

const MAX_LENGTH = 1000;
const TEXTAREA =
  'min-h-20 w-full resize-none rounded-lg border border-input bg-background p-3 text-base placeholder:text-muted-foreground/60 placeholder:italic focus-visible:outline-2 focus-visible:outline-ring';
const LIST = 'mt-2 grid max-h-48 gap-2 overflow-y-auto overscroll-contain pr-1';

/** localStorage key for whether the concerns tile is open; the value is `open` or `collapsed`. */
export const CONCERNS_TILE_KEY = 'tp-concerns-tile';

function readTileOpen(): boolean {
  try {
    return localStorage.getItem(CONCERNS_TILE_KEY) !== 'collapsed';
  } catch {
    // Storage can be blocked (private mode, policy); the tile simply starts open.
    return true;
  }
}

/**
 * Whether the concerns tile is open, remembered per browser. It starts open unless this browser
 * last collapsed it; `forceOpen` (an old `?view=concerns` link) starts it open regardless. Only
 * the word `open` or `collapsed` is stored, never concern text, drafts or trip ids.
 */
export function useConcernsTileOpen(
  forceOpen: boolean,
): readonly [boolean, (open: boolean) => void] {
  const [open, setOpenState] = useState(() => forceOpen || readTileOpen());
  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
    try {
      localStorage.setItem(CONCERNS_TILE_KEY, next ? 'open' : 'collapsed');
    } catch {
      // Private mode: the choice is remembered for this visit only.
    }
  }, []);
  return [open, setOpen] as const;
}

function shortDate(value: string, utc: boolean): string {
  // A plain calendar date (YYYY-MM-DD) must not shift with the viewer's time zone.
  const date = new Date(utc ? `${value}T00:00:00Z` : value);
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(utc ? { timeZone: 'UTC' } : {}),
  });
}

/**
 * Private concerns tile, shown beside the group chat and collapsible to a slim strip. The author
 * sees and can withdraw their own concerns ("Your concerns", newest first). The trip leader also
 * gets what other members wrote ("From the group (anonymous)"): text and date only. The server
 * never sends authors and never puts the caller's own rows in the anonymous list, so neither can
 * be shown here. The body stays mounted while collapsed so a draft survives. The tile never
 * grows the page: the lists scroll inside it. `focusRequest` focuses the textarea whenever it
 * increases (the caller opens the tile first).
 */
export function PrivateConcernsTile({
  tripId,
  isOrganiser,
  open,
  onOpenChange,
  focusRequest = 0,
}: {
  tripId: string;
  isOrganiser: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  focusRequest?: number;
}) {
  const id = useId();
  const bodyId = `${id}-body`;
  const queryClient = useQueryClient();
  const queryKey = ['trip-concerns', tripId];
  const [content, setContent] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);
  const attempt = useRef<{
    content: string;
    client_concern_id: string;
  } | null>(null);
  const query = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}/concerns', {
          params: { path: { trip_id: tripId } },
        }),
      ),
    retry: false,
  });
  const send = useMutation({
    mutationFn: async (body: { content: string; client_concern_id: string }) =>
      unwrap(
        await api.POST('/api/trips/{trip_id}/concerns', {
          params: { path: { trip_id: tripId } },
          body,
        }),
      ),
    onSuccess: () => {
      setContent('');
      attempt.current = null;
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const withdraw = useMutation({
    mutationFn: async (concernId: number) =>
      unwrap(
        await api.POST('/api/trips/{trip_id}/concerns/{concern_id}/withdraw', {
          params: { path: { trip_id: tripId, concern_id: concernId } },
        }),
      ),
    onSuccess: (view) => {
      queryClient.setQueryData(queryKey, view);
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey }),
  });
  useEffect(() => {
    if (focusRequest > 0) field.current?.focus();
  }, [focusRequest]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = content.trim();
    if (text === '' || text.length > MAX_LENGTH || send.isPending) return;
    if (attempt.current?.content !== text) {
      attempt.current = {
        content: text,
        client_concern_id: crypto.randomUUID(),
      };
    }
    send.mutate(attempt.current);
  }

  const capReached =
    send.error instanceof ApiError && send.error.status === 409;
  return (
    <aside
      aria-label="Private concerns"
      className={cn(
        'flex min-w-0 overflow-hidden rounded-2xl border border-border bg-card',
        open
          ? 'min-h-0 w-full max-h-[45dvh] flex-col lg:max-h-none lg:w-[320px] lg:shrink-0 xl:w-[340px]'
          : 'w-full shrink-0 items-center gap-2 p-1.5 lg:w-14 lg:flex-col lg:py-3',
      )}
    >
      <div
        className={cn(
          'flex shrink-0 items-center gap-2',
          open ? 'justify-between px-5 pt-5' : 'lg:flex-col',
        )}
      >
        {open ? (
          <h2 className="flex items-center gap-2.5 text-lg font-semibold">
            <Lock size={20} className="text-primary" aria-hidden="true" />
            Private concerns
          </h2>
        ) : null}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={
            open ? 'Collapse private concerns' : 'Expand private concerns'
          }
          onClick={() => onOpenChange(!open)}
        >
          {open ? (
            <PanelRightClose aria-hidden="true" />
          ) : (
            <PanelRightOpen aria-hidden="true" />
          )}
        </Button>
        {open ? null : (
          <Lock size={18} className="text-primary" aria-hidden="true" />
        )}
        {open ? null : (
          <span className="text-xs font-semibold lg:[writing-mode:vertical-rl]">
            Private concerns
          </span>
        )}
      </div>
      <div
        id={bodyId}
        hidden={!open}
        className={
          open ? 'flex min-h-0 flex-1 flex-col gap-4 px-5 pt-3 pb-5' : 'hidden'
        }
      >
        <div className="flex shrink-0 flex-col gap-3">
          <p className="text-xs leading-relaxed text-muted-foreground">
            Only you and the trip leader can read these. The leader sees what
            you wrote, never your name, but in a small group they may still be
            able to guess who wrote it. Other members never see them.
          </p>
          <form onSubmit={submit} className="grid gap-2">
            <label htmlFor={`${id}-concern`} className="font-semibold">
              Share a private concern
            </label>
            <textarea
              ref={field}
              id={`${id}-concern`}
              value={content}
              rows={3}
              maxLength={MAX_LENGTH}
              disabled={send.isPending}
              onChange={(event) => {
                setContent(event.target.value);
                send.reset();
              }}
              className={TEXTAREA}
              placeholder="Ex. the boat tour is more than I want to spend"
            />
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">
                {content.length}/{MAX_LENGTH}
              </span>
              <Button
                type="submit"
                disabled={!content.trim() || send.isPending}
                aria-busy={send.isPending}
              >
                {send.isPending ? 'Sending…' : 'Send privately'}
              </Button>
            </div>
            {send.isError && (
              <p role="alert" className="text-sm text-destructive">
                {capReached
                  ? send.error.message
                  : 'Couldn’t send your concern. Your draft is still here; try again.'}
              </p>
            )}
          </form>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain">
          {query.isPending ? (
            <p aria-busy="true">Loading private concerns…</p>
          ) : query.isError ? (
            <ErrorRetry as="h2" onRetry={() => void query.refetch()} />
          ) : (
            <>
              <section aria-labelledby={`${id}-mine`}>
                <h3 id={`${id}-mine`} className="text-sm font-semibold">
                  Your concerns
                </h3>
                {query.data.mine.length === 0 ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    You haven’t shared anything privately.
                  </p>
                ) : (
                  <ul className={LIST}>
                    {query.data.mine.map((item) => (
                      <li
                        key={item.id}
                        className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="whitespace-pre-wrap break-words text-sm [overflow-wrap:anywhere]">
                            {item.content}
                          </p>
                          <p className="mt-1.5 flex items-center gap-2">
                            <Badge>You</Badge>
                            <span className="text-xs text-muted-foreground">
                              {shortDate(item.created_at, false)}
                            </span>
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={withdraw.isPending}
                          aria-label={`Withdraw concern from ${shortDate(item.created_at, false)}`}
                          onClick={() => withdraw.mutate(item.id)}
                        >
                          Withdraw
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                {withdraw.isError && (
                  <p role="alert" className="mt-2 text-sm text-destructive">
                    Couldn’t withdraw that concern. Try again.
                  </p>
                )}
              </section>
              {isOrganiser && query.data.anonymous && (
                <section aria-labelledby={`${id}-anonymous`}>
                  <h3 id={`${id}-anonymous`} className="text-sm font-semibold">
                    From the group (anonymous)
                  </h3>
                  {query.data.anonymous.length === 0 ? (
                    <p className="mt-2 text-sm text-muted-foreground">
                      Nothing from the group yet.
                    </p>
                  ) : (
                    <ul className={LIST}>
                      {query.data.anonymous.map((item, index) => (
                        <li
                          // The server sends no ids on purpose; order is stable and the list is read-only.
                          // biome-ignore lint/suspicious/noArrayIndexKey: no id exists for an anonymous item
                          key={index}
                          className="rounded-lg border border-border bg-muted/60 p-3"
                        >
                          <p className="whitespace-pre-wrap break-words text-sm [overflow-wrap:anywhere]">
                            {item.content}
                          </p>
                          <p className="mt-1.5 text-xs text-muted-foreground">
                            {shortDate(item.submitted_on, true)}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
