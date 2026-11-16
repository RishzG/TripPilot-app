import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useRef, useState } from 'react';
import { shownName } from '@/components/Avatar';
import { ErrorRetry } from '@/components/ErrorRetry';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ApiError, api, unwrap } from '@/lib/api';
import type { components } from '@/lib/api-types';
import { budgetCents } from '../trips/TravelPreferencesPanel';
import { EmptyPlan, type WorkspaceView } from '../trips/TripWorkspace';

import { PilotPanel } from './PilotPanel';
import { ReplanningPanel } from './ReplanningPanel';

type Draft = components['schemas']['PlanVersionView'];
type SaveDraft = components['schemas']['CreatePlanVersion'];
type Item = components['schemas']['PlanItemInput'];
type Context = components['schemas']['TripPlanningContext'];
type Member = components['schemas']['MemberView'];
type EditableItem = Omit<Item, 'estimated_cents'> & { cost: string };

const ROUTE = '/api/trips/{trip_id}/plans';
const MAX_ITEMS = 60;
const dollars = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});
const calendarDay = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'full',
  timeZone: 'UTC',
});
const money = (cents: number | null) =>
  cents === null ? 'Estimate pending' : dollars.format(cents / 100);

function DraftEditor({
  base,
  members,
  onSave,
  onClose,
  saving,
  error,
}: {
  base: Draft | null;
  members: Member[];
  onSave: (body: SaveDraft) => void;
  onClose: () => void;
  saving: boolean;
  error: string | null;
}) {
  const [items, setItems] = useState<EditableItem[]>(() =>
    (base?.items ?? []).map((item) => ({
      id: item.id,
      title: item.title,
      day: item.day,
      location: item.location,
      participant_ids: item.participant_ids,
      cost:
        item.estimated_cents === null
          ? ''
          : (item.estimated_cents / 100).toFixed(2),
    })),
  );
  const [validation, setValidation] = useState<string | null>(null);
  const attempt = useRef<{ payload: string; requestId: string } | null>(null);

  function update(id: string, patch: Partial<EditableItem>) {
    setItems((rows) =>
      rows.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
    setValidation(null);
  }

  function addItem() {
    setItems((rows) => [
      ...rows,
      {
        id: crypto.randomUUID(),
        day: rows.at(-1)?.day ?? '',
        title: '',
        location: '',
        cost: '',
        participant_ids: members.map((member) => member.account_id),
      },
    ]);
    setValidation(null);
  }

  const activeIds = new Set(members.map((member) => member.account_id));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setValidation(null);
    try {
      const parsed = items.map(({ cost, ...item }, index) => {
        if (!item.title.trim())
          throw new Error(`Enter a title for item ${index + 1}.`);
        if (
          !item.participant_ids.length ||
          item.participant_ids.some((id) => !activeIds.has(id))
        ) {
          throw new Error(`Choose active participants for item ${index + 1}.`);
        }
        try {
          return { ...item, estimated_cents: budgetCents(cost) };
        } catch {
          throw new Error(
            `Enter an estimate from $0 to $1,000,000 with up to two decimal places for item ${index + 1}.`,
          );
        }
      });
      const draft = { base_version: base?.version ?? 0, items: parsed };
      const payload = JSON.stringify(draft);
      if (attempt.current?.payload !== payload) {
        attempt.current = { payload, requestId: crypto.randomUUID() };
      }
      onSave({ ...draft, request_id: attempt.current.requestId });
    } catch (reason) {
      setValidation(
        reason instanceof Error
          ? reason.message
          : 'Check the itinerary and try again.',
      );
    }
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold">
          {base ? 'Revise the itinerary' : 'Create an itinerary'}
        </h2>
        <p className="text-sm text-muted-foreground">
          Saving creates a new draft version. Estimates are in USD. Leave the
          cost blank if it is unknown.
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit}>
          <fieldset disabled={saving} className="space-y-5">
            {items.map((item, index) => (
              <fieldset
                key={item.id}
                className="space-y-4 rounded-xl border border-border p-4"
              >
                <legend className="px-1 font-semibold">Item {index + 1}</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label
                    htmlFor={`title-${item.id}`}
                    className="grid gap-1 text-sm"
                  >
                    Activity
                    <Input
                      id={`title-${item.id}`}
                      required
                      maxLength={120}
                      value={item.title}
                      onChange={(event) =>
                        update(item.id, { title: event.target.value })
                      }
                    />
                  </label>
                  <label
                    htmlFor={`date-${item.id}`}
                    className="grid gap-1 text-sm"
                  >
                    Date
                    <Input
                      id={`date-${item.id}`}
                      required
                      type="date"
                      value={item.day}
                      onChange={(event) =>
                        update(item.id, { day: event.target.value })
                      }
                    />
                  </label>
                  <label
                    htmlFor={`location-${item.id}`}
                    className="grid gap-1 text-sm"
                  >
                    Location (optional)
                    <Input
                      id={`location-${item.id}`}
                      maxLength={160}
                      value={item.location}
                      onChange={(event) =>
                        update(item.id, { location: event.target.value })
                      }
                    />
                  </label>
                  <label
                    htmlFor={`cost-${item.id}`}
                    className="grid gap-1 text-sm"
                  >
                    Estimated total (USD)
                    <Input
                      id={`cost-${item.id}`}
                      inputMode="decimal"
                      placeholder="e.g. 45.00"
                      value={item.cost}
                      onChange={(event) =>
                        update(item.id, { cost: event.target.value })
                      }
                    />
                  </label>
                </div>
                <fieldset>
                  <legend className="mb-1 text-sm font-medium">
                    Split equally among
                  </legend>
                  <div className="flex flex-wrap gap-x-5 gap-y-2">
                    {members.map((member) => {
                      const id = member.account_id;
                      return (
                        <label
                          key={id}
                          className="flex items-center gap-2 text-sm"
                        >
                          <input
                            type="checkbox"
                            checked={item.participant_ids.includes(id)}
                            onChange={(event) =>
                              update(item.id, {
                                participant_ids: event.target.checked
                                  ? [...item.participant_ids, id]
                                  : item.participant_ids.filter(
                                      (selected) => selected !== id,
                                    ),
                              })
                            }
                          />
                          {shownName(member)}
                        </label>
                      );
                    })}
                  </div>
                  {item.participant_ids.some((id) => !activeIds.has(id)) && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                      <span>
                        Some selected participants have left the trip.
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          update(item.id, {
                            participant_ids: item.participant_ids.filter((id) =>
                              activeIds.has(id),
                            ),
                          })
                        }
                      >
                        Remove inactive participants from this item
                      </Button>
                    </div>
                  )}
                </fieldset>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label={`Remove item ${index + 1}`}
                  onClick={() => {
                    setItems((rows) =>
                      rows.filter((row) => row.id !== item.id),
                    );
                    setValidation(null);
                  }}
                >
                  Remove item
                </Button>
              </fieldset>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={items.length >= MAX_ITEMS}
                onClick={addItem}
              >
                Add item
              </Button>
              <Button
                type="submit"
                disabled={items.length === 0 && base === null}
              >
                {saving ? 'Saving…' : 'Save draft version'}
              </Button>
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
            </div>
          </fieldset>
          {(validation ?? error) && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {validation ?? error}
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

function DraftDetails({ draft }: { draft: Draft }) {
  const days = new Map<string, Draft['items']>();
  for (const item of draft.items) {
    const day = days.get(item.day);
    if (day) day.push(item);
    else days.set(item.day, [item]);
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="space-y-5">
        {days.size === 0 && (
          <p className="text-sm text-muted-foreground">
            This draft has no items.
          </p>
        )}
        {[...days].map(([day, items]) => (
          <Card key={day}>
            <CardHeader>
              <h3 className="font-semibold">
                <time dateTime={day}>{calendarDay.format(new Date(day))}</time>
              </h3>
            </CardHeader>
            <CardContent>
              <ul className="divide-y divide-border">
                {items.map((item) => (
                  <li
                    key={item.id}
                    className="space-y-2 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="flex flex-wrap justify-between gap-2">
                      <h4 className="break-words font-semibold">
                        {item.title}
                      </h4>
                      <span className="text-sm tabular-nums">
                        {money(item.estimated_cents)}
                      </span>
                    </div>
                    {item.location && (
                      <p className="break-words text-sm text-muted-foreground">
                        {item.location}
                      </p>
                    )}
                    {item.source && (
                      <p className="text-xs text-muted-foreground">
                        <a
                          href={item.source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-primary underline"
                        >
                          {item.source.title}
                        </a>
                        {' · Checked '}
                        {item.source.checked_on}
                        {'. '}
                        {item.source.estimate_note}
                        {' Check the venue for your dates.'}
                      </p>
                    )}
                    <ul
                      className="flex flex-wrap gap-2"
                      aria-label={`Estimated shares for ${item.title}`}
                    >
                      {item.shares.map((share) => (
                        <li
                          key={share.account_id}
                          className="rounded-md bg-muted px-2 py-1 text-xs"
                        >
                          {share.name} · {money(share.cents)}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <h3 className="font-semibold">Estimated split</h3>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-2xl font-semibold tabular-nums">
            {draft.items.length > 0 &&
            draft.unpriced_items === draft.items.length
              ? 'Estimate pending'
              : money(draft.estimated_total_cents)}
          </p>
          <p className="text-xs text-muted-foreground">
            Total of priced items in USD. Estimates are for planning only.
          </p>
          {draft.unpriced_items > 0 && (
            <p className="text-xs text-muted-foreground">
              {draft.unpriced_items}{' '}
              {draft.unpriced_items === 1 ? 'item has' : 'items have'} no
              estimate yet.
            </p>
          )}
          <ul className="space-y-2 border-t border-border pt-3 text-sm">
            {draft.member_totals.map((share) => (
              <li key={share.account_id} className="flex justify-between gap-2">
                <span className="break-words">{share.name}</span>
                <span className="shrink-0 tabular-nums">
                  {money(share.cents)}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

export function ItineraryPanel({
  tripId,
  members,
  isOrganiser,
  context,
  currentVersion,
  viewerId,
  onNavigate,
}: {
  tripId: string;
  members: Member[];
  isOrganiser: boolean;
  context: Context | null;
  currentVersion: number | null;
  viewerId: string | undefined;
  onNavigate: (view: WorkspaceView) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<{ base: Draft | null } | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const path = { trip_id: tripId };
  const queryKey = ['trip-plan', tripId, 'latest'];
  const latest = useQuery({
    queryKey,
    queryFn: async ({ signal }) =>
      unwrap(await api.GET(ROUTE, { params: { path }, signal })),
    retry: false,
  });
  const current = latest.data?.draft ?? null;
  const viewingHistory = version !== null && version !== current?.version;
  const history = useQuery({
    queryKey: ['trip-plan', tripId, version],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET(ROUTE, {
          params: { path, query: { version: version ?? undefined } },
          signal,
        }),
      ),
    enabled: viewingHistory,
    retry: false,
  });
  const save = useMutation({
    mutationFn: async (body: SaveDraft) =>
      unwrap(await api.POST(ROUTE, { params: { path }, body })),
    onSuccess: async (draft) => {
      setEditing(null);
      setVersion(null);
      await queryClient.cancelQueries({ queryKey, exact: true });
      queryClient.setQueryData<typeof latest.data>(queryKey, (current) =>
        (current?.draft?.version ?? 0) > draft.version ? current : { draft },
      );
      void queryClient.invalidateQueries({ queryKey, exact: true });
    },
  });

  const selected = viewingHistory ? history : latest;
  const draft = selected.data?.draft ?? null;
  function openVersion(number: number) {
    void latest.refetch();
    setVersion(number === current?.version ? null : number);
  }
  if (editing && isOrganiser) {
    return (
      <DraftEditor
        base={editing.base}
        members={members}
        onSave={save.mutate}
        saving={save.isPending}
        error={
          save.error instanceof ApiError && save.error.status === 409
            ? 'A newer draft is available. Copy any edits you want to keep, then cancel and reopen the latest draft.'
            : save.isError
              ? 'Could not save the draft. Check your inputs and try again.'
              : null
        }
        onClose={() => {
          setEditing(null);
          void latest.refetch();
        }}
      />
    );
  }

  if (latest.isPending) return <p role="status">Loading itinerary…</p>;
  if (latest.isError)
    return <ErrorRetry onRetry={() => void latest.refetch()} />;

  return (
    <section className="space-y-5" aria-label="Itinerary drafts">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Itinerary</h2>
          <p className="text-sm text-muted-foreground">
            Browse drafts and see how estimated costs are shared.
          </p>
        </div>
        {isOrganiser && !viewingHistory && (
          <Button
            type="button"
            onClick={() => {
              save.reset();
              setEditing({ base: current });
            }}
          >
            {current ? 'Revise itinerary' : 'Create draft'}
          </Button>
        )}
      </header>
      <div
        className={
          current === null && version === null
            ? 'grid items-start gap-5 lg:grid-cols-2'
            : 'space-y-5'
        }
      >
        <PilotPanel
          tripId={tripId}
          context={context}
          isOrganiser={isOrganiser}
          onOpenDraft={openVersion}
        />
        {current === null && version === null ? (
          <EmptyPlan onNavigate={onNavigate} />
        ) : (
          <>
            <ReplanningPanel
              tripId={tripId}
              viewed={draft}
              currentVersion={currentVersion}
              members={members}
              viewerId={viewerId}
              organiser={isOrganiser}
              onOpen={openVersion}
            />
            <nav
              aria-label="Draft history"
              className="flex flex-wrap items-center gap-2"
            >
              <span className="mr-2 text-sm font-semibold">
                {currentVersion === null
                  ? 'Draft'
                  : draft?.version === currentVersion
                    ? 'Current version'
                    : 'Version'}{' '}
                v{version ?? current?.version} of {current?.version ?? version}
              </span>
              <Button
                type="button"
                variant="outline"
                disabled={(version ?? current?.version ?? 1) <= 1}
                onClick={() =>
                  setVersion((version ?? current?.version ?? 1) - 1)
                }
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!viewingHistory}
                onClick={() =>
                  setVersion(
                    version === null ||
                      version + 1 >= (current?.version ?? version)
                      ? null
                      : version + 1,
                  )
                }
              >
                Next
              </Button>
              {viewingHistory && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setVersion(null)}
                >
                  Latest draft
                </Button>
              )}
            </nav>
            {selected.isPending && <p role="status">Loading draft…</p>}
            {selected.isError && (
              <ErrorRetry onRetry={() => void selected.refetch()} />
            )}
            {draft && <DraftDetails draft={draft} />}
          </>
        )}
      </div>
    </section>
  );
}
