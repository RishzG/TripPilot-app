import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { MessageCircle } from 'lucide-react';
import {
  type FormEvent,
  Fragment,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Avatar } from '@/components/Avatar';
import { ErrorRetry } from '@/components/ErrorRetry';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/api-types';
import { cn } from '@/lib/utils';

type History = components['schemas']['MessageHistory'];
type Message = components['schemas']['MessageView'];
type ChatData = InfiniteData<History, number | null>;
const MAX_LENGTH = 4000;
const chatDay = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });
const chatTime = new Intl.DateTimeFormat(undefined, { timeStyle: 'short' });

/** Keep the reader's place on older-page loads; follow new messages only near the bottom. */
function MessageList({
  messages,
  viewerId,
  fill,
  active,
}: {
  messages: Message[];
  viewerId: string | undefined;
  fill: boolean;
  active: boolean;
}) {
  const list = useRef<HTMLUListElement>(null);
  const follow = useRef(true);
  const previous = useRef<{
    height: number;
    first: number;
    last: number;
  } | null>(null);
  useLayoutEffect(() => {
    if (!active) return;
    const element = list.current;
    const first = messages[0]?.id;
    const last = messages.at(-1)?.id;
    if (!element || first === undefined || last === undefined) return;
    const old = previous.current;
    if (old && first !== old.first && last === old.last) {
      element.scrollTop += element.scrollHeight - old.height;
    } else if (follow.current) {
      element.scrollTop = element.scrollHeight;
    }
    previous.current = { height: element.scrollHeight, first, last };
  }, [messages, active]);
  return (
    <ul
      ref={list}
      role="log"
      aria-label="Group messages"
      aria-live="polite"
      aria-relevant="additions"
      className={cn(
        'overflow-y-auto overscroll-contain pr-1',
        fill ? 'min-h-0 flex-1' : 'max-h-96',
      )}
      onScroll={(event) => {
        const target = event.currentTarget;
        follow.current =
          target.scrollHeight - target.clientHeight - target.scrollTop < 64;
      }}
    >
      {messages.map((message, index) => {
        const own = message.account_id === viewerId;
        const sent = new Date(message.created_at);
        const previous = messages[index - 1];
        const startsDay =
          previous === undefined ||
          new Date(previous.created_at).toDateString() !== sent.toDateString();
        return (
          <Fragment key={message.id}>
            {startsDay && (
              <li className="flex justify-center py-3 first:pt-0">
                <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                  {chatDay.format(sent)}
                </span>
              </li>
            )}
            <li
              className={cn(
                'flex min-w-0 items-start gap-2.5 py-1.5 last:pb-0',
                own && 'justify-end',
              )}
            >
              {!own && (
                <Avatar
                  name={message.author_name}
                  kind="initials"
                  avatarKey={null}
                  size={32}
                />
              )}
              <div
                className={cn(
                  'min-w-0 max-w-[75ch] rounded-xl px-3 py-2 text-sm',
                  own
                    ? 'rounded-tr-sm bg-primary/10'
                    : 'rounded-tl-sm bg-muted/70',
                )}
              >
                {!own && (
                  <p className="mb-0.5 break-words font-semibold [overflow-wrap:anywhere]">
                    {message.author_name}
                  </p>
                )}
                <div className="flex flex-wrap items-end justify-end gap-x-3">
                  <p className="min-w-0 max-w-full leading-relaxed whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                    {message.content}
                  </p>
                  <time
                    dateTime={message.created_at}
                    className="shrink-0 text-[11px] text-muted-foreground"
                  >
                    {chatTime.format(sent)}
                  </time>
                </div>
              </div>
            </li>
          </Fragment>
        );
      })}
    </ul>
  );
}

/**
 * Public trip discussion only. Text (including `/plan`) never executes a command.
 * `onShareConcern` adds a link that expands and focuses the private concerns tile.
 */
export function GroupChat({
  tripId,
  viewerId,
  fill = false,
  active = true,
  onShareConcern,
}: {
  tripId: string;
  viewerId: string | undefined;
  fill?: boolean;
  active?: boolean;
  onShareConcern?: () => void;
}) {
  const labelId = useId();
  const queryClient = useQueryClient();
  const queryKey = useMemo(() => ['trip-messages', tripId], [tripId]);
  const [content, setContent] = useState('');
  const composer = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const field = composer.current;
    if (!field || !active) return;
    field.style.height = 'auto';
    const height =
      content.length === 0
        ? 52
        : Math.max(52, Math.min(field.scrollHeight, 120));
    field.style.height = `${height}px`;
  }, [content, active]);
  const attempt = useRef<{ content: string; client_message_id: string } | null>(
    null,
  );
  const history = useInfiniteQuery({
    queryKey,
    initialPageParam: null as number | null,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/api/trips/{trip_id}/messages', {
          params: {
            path: { trip_id: tripId },
            query: {
              limit: 30,
              ...(pageParam === null ? {} : { before: pageParam }),
            },
          },
        }),
      ),
    getNextPageParam: (lastPage) => lastPage.older_cursor,
    retry: false,
  });
  const messages = useMemo(() => {
    const byId = new Map<number, Message>();
    for (const page of history.data?.pages ?? []) {
      for (const message of page.messages) byId.set(message.id, message);
    }
    return [...byId.values()].sort((a, b) => a.id - b.id);
  }, [history.data]);
  const send = useMutation({
    mutationFn: async (body: { content: string; client_message_id: string }) =>
      unwrap(
        await api.POST('/api/trips/{trip_id}/messages', {
          params: { path: { trip_id: tripId } },
          body,
        }),
      ),
    onSuccess: async (message) => {
      await queryClient.cancelQueries({ queryKey });
      queryClient.setQueryData<ChatData>(queryKey, (current) => {
        if (!current)
          return {
            pages: [{ messages: [message], older_cursor: null }],
            pageParams: [null],
          };
        if (
          current.pages.some((page) =>
            page.messages.some((item) => item.id === message.id),
          )
        )
          return current;
        return {
          ...current,
          pages: current.pages.map((page, index) =>
            index === 0
              ? { ...page, messages: [...page.messages, message] }
              : page,
          ),
        };
      });
      setContent('');
      attempt.current = null;
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = content.trim();
    if (text === '' || text.length > MAX_LENGTH || send.isPending) return;
    if (attempt.current?.content !== text) {
      attempt.current = {
        content: text,
        client_message_id: crypto.randomUUID(),
      };
    }
    send.mutate(attempt.current);
  }

  return (
    <Card
      className={cn(
        'min-w-0 rounded-2xl',
        fill &&
          'h-full min-h-0 gap-4 [--card-spacing:--spacing(5)] md:[--card-spacing:--spacing(5)]',
      )}
    >
      <CardHeader>
        <h2 className="flex items-center gap-2.5 text-lg font-semibold">
          <MessageCircle
            size={20}
            className="text-primary"
            aria-hidden="true"
          />
          Group chat
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          <span id={`${labelId}-visibility`}>
            Everyone in this trip can read these messages.
          </span>
          {onShareConcern && (
            <>
              {' '}
              <button
                type="button"
                className="underline underline-offset-2 hover:text-foreground"
                onClick={onShareConcern}
              >
                Share something privately
              </button>
            </>
          )}
        </p>
      </CardHeader>
      <CardContent
        className={cn('flex min-w-0 flex-col gap-4', fill && 'min-h-0 flex-1')}
      >
        {history.isPending ? (
          <p aria-busy="true">Loading messages…</p>
        ) : !history.data ? (
          <ErrorRetry onRetry={() => void history.refetch()} />
        ) : (
          <>
            {history.hasNextPage && (
              <Button
                type="button"
                variant="outline"
                disabled={history.isFetchingNextPage}
                onClick={() => void history.fetchNextPage()}
              >
                {history.isFetchingNextPage
                  ? 'Loading older messages…'
                  : 'Load older messages'}
              </Button>
            )}
            {messages.length ? (
              <MessageList
                messages={messages}
                viewerId={viewerId}
                fill={fill}
                active={active}
              />
            ) : (
              <div
                className={cn(
                  'py-8 text-center',
                  fill && 'flex flex-1 flex-col items-center justify-center',
                )}
              >
                <span className="mb-4 inline-flex size-12 items-center justify-center rounded-full bg-muted">
                  <MessageCircle
                    size={22}
                    className="text-primary"
                    aria-hidden="true"
                  />
                </span>
                <p className="mb-2 font-semibold">Start the conversation</p>
                <p className="max-w-xs text-sm leading-relaxed text-muted-foreground">
                  No messages yet. Start with where you’d like to go or what
                  you’d like to do.
                </p>
              </div>
            )}
            {history.isError && (
              <p role="alert" className="text-sm text-destructive">
                Couldn’t refresh messages.{' '}
                <button
                  type="button"
                  className="underline"
                  onClick={() => void history.refetch()}
                >
                  Try again
                </button>
              </p>
            )}
            <form
              onSubmit={submit}
              className="mt-auto flex shrink-0 flex-col gap-2 border-t border-border pt-3"
            >
              <label htmlFor={labelId} className="sr-only">
                Message the group
              </label>
              <div className="flex items-end gap-3">
                <textarea
                  ref={composer}
                  id={labelId}
                  value={content}
                  maxLength={MAX_LENGTH}
                  disabled={send.isPending}
                  onChange={(event) => {
                    setContent(event.target.value);
                    send.reset();
                  }}
                  aria-describedby={`${labelId}-help ${labelId}-visibility`}
                  onKeyDown={(event) => {
                    if (
                      event.key === 'Enter' &&
                      (event.ctrlKey || event.metaKey) &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  placeholder="Ex. a place you’d love to visit…"
                  className="h-13 min-h-13 min-w-0 flex-1 resize-none rounded-xl border border-input bg-background p-3 text-sm placeholder:text-muted-foreground/60 placeholder:italic focus-visible:outline-2 focus-visible:outline-ring"
                />
                <Button
                  type="submit"
                  className="shrink-0"
                  disabled={!content.trim() || send.isPending}
                  aria-busy={send.isPending}
                >
                  {send.isPending ? 'Sending…' : 'Send message'}
                </Button>
              </div>
              <div className="flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
                <p id={`${labelId}-help`}>
                  Enter for a new line · Ctrl/⌘ + Enter to send
                </p>
                <span className="shrink-0">
                  {content.length}/{MAX_LENGTH}
                </span>
              </div>
              {send.isError && (
                <p role="alert" className="text-sm text-destructive">
                  Couldn’t send your message. Your draft is still here; try
                  again.
                </p>
              )}
            </form>
          </>
        )}
      </CardContent>
    </Card>
  );
}
