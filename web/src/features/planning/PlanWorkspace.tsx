import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useRef, useState } from 'react';

import { ErrorRetry } from '@/components/ErrorRetry';

import { Badge } from '@/components/ui/badge';

import { Button } from '@/components/ui/button';

import { api, unwrap } from '@/lib/api';

import type { components } from '@/lib/api-types';

import { useMe } from '../auth/useMe';

type Context = components['schemas']['TripContext'];

type Item = components['schemas']['PlanItem'];

type Member = components['schemas']['MemberView'];

const FIELD = 'w-full rounded-lg border border-input bg-background p-2 text-sm';

const CARD = 'rounded-2xl border border-border bg-card p-5';

const money = (cents: number) =>
  new Intl.NumberFormat(undefined, {
    style: 'currency',

    currency: 'USD',
  }).format(cents / 100);

function ContextEditor({
  initial,

  save,

  pending,
}: {
  initial: Context;

  save: (context: Context) => void;

  pending: boolean;
}) {
  const [draft, setDraft] = useState(initial);

  return (
    <form
      className="grid gap-4 md:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();

        save(draft);
      }}
    >
      <label className="grid gap-1 text-sm">
        Trip name
        <input
          className={FIELD}
          required
          maxLength={80}
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
      </label>
      <label className="grid gap-1 text-sm">
        Destination
        <input
          className={FIELD}
          maxLength={160}
          value={draft.destination}
          placeholder="City or region"
          onChange={(e) => setDraft({ ...draft, destination: e.target.value })}
        />
      </label>
      <label className="grid gap-1 text-sm">
        Start date
        <input
          className={FIELD}
          type="date"
          value={draft.start_date ?? ''}
          onChange={(e) =>
            setDraft({ ...draft, start_date: e.target.value || null })
          }
        />
      </label>
      <label className="grid gap-1 text-sm">
        End date
        <input
          className={FIELD}
          type="date"
          min={draft.start_date ?? undefined}
          value={draft.end_date ?? ''}
          onChange={(e) =>
            setDraft({ ...draft, end_date: e.target.value || null })
          }
        />
      </label>
      <label className="grid gap-1 text-sm">
        Trip timezone
        <input
          className={FIELD}
          required
          value={draft.timezone}
          placeholder="America/Chicago"
          onChange={(e) => setDraft({ ...draft, timezone: e.target.value })}
        />
        <span className="text-xs text-muted-foreground">
          IANA timezone; itinerary times use this timezone.
        </span>
      </label>
      <Button className="self-end" type="submit" disabled={pending}>
        Save trip details
      </Button>
    </form>
  );
}

function ItineraryMap({ items }: { items: Item[] }) {
  const [focused, setFocused] = useState('');

  const point = items.find((item) => item.id === focused) ?? items[0];

  if (!point) return null;

  const lats = items.map((item) => item.latitude);

  const lons = items.map((item) => item.longitude);

  const params = new URLSearchParams({
    bbox: `${Math.min(...lons) - 0.01},${Math.min(...lats) - 0.01},${Math.max(...lons) + 0.01},${Math.max(...lats) + 0.01}`,

    layer: 'mapnik',

    marker: `${point.latitude},${point.longitude}`,
  });

  return (
    <section className={CARD} aria-label="Itinerary map">
      <h3 className="mb-3 font-semibold">Places on this day</h3>
      <iframe
        title={`Itinerary map: ${point.location}`}
        className="h-72 w-full rounded-xl border-0"
        loading="lazy"
        referrerPolicy="no-referrer"
        src={`https://www.openstreetmap.org/export/embed.html?${params}`}
      />
      <p className="mt-2 text-xs text-muted-foreground">
        Map data ©{' '}
        <a
          className="underline"
          href="https://www.openstreetmap.org/copyright"
          target="_blank"
          rel="noreferrer"
        >
          OpenStreetMap contributors
        </a>
        . Pins show places, not verified routes or travel times.
      </p>
      <ul className="mt-3 flex flex-wrap gap-2">
        {items.map((item, index) => (
          <li key={item.id}>
            <Button
              variant={item.id === point.id ? 'default' : 'outline'}
              aria-pressed={item.id === point.id}
              onClick={() => setFocused(item.id)}
            >
              {index + 1}. {item.location}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PlanWorkspace({
  tripId,

  isOrganiser,

  members,
}: {
  tripId: string;

  isOrganiser: boolean;

  members: Member[];
}) {
  const client = useQueryClient();

  const me = useMe();

  const key = ['trip-planning', tripId];

  const [versionId, setVersionId] = useState('');

  const [day, setDay] = useState('');

  const [cancelledId, setCancelledId] = useState('');

  const invocationId = useRef<{ key: string; id: string } | null>(null);

  const query = useQuery({
    queryKey: key,

    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}/planning', {
          params: { path: { trip_id: tripId } },
        }),
      ),

    refetchInterval: (query) =>
      query.state.data?.runs.some(
        (run) => run.status === 'queued' || run.status === 'running',
      )
        ? 3000
        : false,
  });

  const action = useMutation({
    mutationFn: (operation: () => Promise<unknown>) => operation(),

    onSuccess: () => {
      void client.invalidateQueries({ queryKey: key });

      void client.invalidateQueries({ queryKey: ['trip', tripId] });
    },
  });

  if (query.isPending)
    return <p aria-busy="true">Loading the plan workspace…</p>;

  if (query.isError) return <ErrorRetry onRetry={() => void query.refetch()} />;

  const data = query.data;

  const selected = data.versions.find(
    (version) => version.id === data.selected_id,
  );

  const version =
    data.versions.find((item) => item.id === versionId) ??
    selected ??
    data.versions[0];

  const days = [
    ...new Set(version?.items.map((item) => item.day) ?? []),
  ].sort();

  const activeDay = days.includes(day) ? day : days[0];

  const items =
    version?.items

      .filter((item) => item.day === activeDay)

      .sort((a, b) => a.starts_at.localeCompare(b.starts_at)) ?? [];

  const cancelled = selected?.items.find((item) => item.id === cancelledId);

  const alternatives = cancelled
    ? data.versions

        .filter(
          (v) =>
            v.id !== selected?.id && v.sample === selected?.sample && v.current,
        )

        .flatMap((v) =>
          v.items

            .filter(
              (item) =>
                item.day === cancelled.day &&
                !selected?.items.some(
                  (existing) =>
                    existing.id === item.id ||
                    existing.location === item.location,
                ),
            )

            .map((item) => ({ version: v, item })),
        )
    : [];

  const memberName = (id: string) => {
    const member = members.find((item) => item.account_id === id);

    return member ? member.nickname || member.display_name : 'Former member';
  };

  const activeRun = data.runs.find(
    (run) => run.status === 'queued' || run.status === 'running',
  );

  function runPilot() {
    const requestKey = `${data.context.revision}-${selected?.id ?? ''}-${cancelled?.id ?? ''}`;

    if (invocationId.current?.key !== requestKey) {
      invocationId.current = { key: requestKey, id: crypto.randomUUID() };
    }

    const clientId = invocationId.current.id;

    action.mutate(async () => {
      const result = unwrap(
        await api.POST('/api/trips/{trip_id}/planning/runs', {
          params: { path: { trip_id: tripId } },

          body: {
            client_id: clientId,

            base_id: cancelled ? selected?.id : null,

            cancelled_item_id: cancelled?.id ?? null,
          },
        }),
      );

      invocationId.current = null;

      return result;
    });
  }

  return (
    <div className="space-y-6 pb-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Your shared itinerary</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            A plan that fits the group, with the tradeoffs made clear.
          </p>
        </div>
        {isOrganiser && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={action.isPending || data.versions.some((v) => v.sample)}
              onClick={() =>
                action.mutate(async () =>
                  unwrap(
                    await api.POST('/api/trips/{trip_id}/planning/sample', {
                      params: { path: { trip_id: tripId } },
                    }),
                  ),
                )
              }
            >
              Load Chicago sample
            </Button>
            <Button
              disabled={
                action.isPending || !!activeRun || !data.pilot_configured
              }
              onClick={runPilot}
            >
              {activeRun
                ? 'Pilot is working…'
                : cancelled
                  ? 'Research alternatives'
                  : 'Plan with Pilot'}
            </Button>
          </div>
        )}
      </header>
      {action.isError && (
        <p
          role="alert"
          className="rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {action.error.message}
        </p>
      )}
      <section className={CARD} aria-label="Shared trip details">
        <details open={!data.context.start_date || !data.context.destination}>
          <summary className="cursor-pointer font-semibold">
            <span>Where and when</span>
            <span className="ml-3 text-sm font-normal text-muted-foreground">
              {data.context.destination || 'Choose a destination'} ·{' '}
              {data.context.start_date ?? 'Set dates'} —{' '}
              {data.context.end_date ?? ''} · {data.context.timezone}
            </span>
          </summary>
          <div className="mt-4">
            {isOrganiser ? (
              <ContextEditor
                key={data.context.revision}
                initial={data.context}
                pending={action.isPending}
                save={(context) =>
                  action.mutate(async () =>
                    unwrap(
                      await api.PUT('/api/trips/{trip_id}/planning/context', {
                        params: { path: { trip_id: tripId } },

                        body: context,
                      }),
                    ),
                  )
                }
              />
            ) : (
              <p>
                {data.context.destination || 'Destination to be decided'} ·{' '}
                {data.context.start_date ?? 'Dates to be decided'} —{' '}
                {data.context.end_date ?? ''} · {data.context.timezone}
              </p>
            )}
          </div>
        </details>
      </section>
      <p className="text-sm text-muted-foreground">
        Pilot uses private concerns, budget ceilings and dietary notes to check
        fit. These inputs stay out of public research and the shared itinerary.
        Your explanation is private to you. Hard constraints must be met;
        uncertainty or conflicting requirements may prevent a draft. Estimates
        need confirmation and do not include unlisted travel or lodging. Pilot’s
        model provider processes your private inputs for fit checks.
      </p>
      {!data.pilot_configured && (
        <p className="text-sm text-muted-foreground">
          Live Pilot needs an AI Gateway connection configured by the
          administrator. You can explore the clearly labeled sample now.
        </p>
      )}
      {data.runs.length > 0 && (
        <section className={CARD} aria-label="Pilot requests">
          <h3 className="font-semibold">Pilot requests</h3>
          <ul className="mt-3 space-y-2">
            {data.runs.slice(0, 5).map((run) => (
              <li key={run.id} className="text-sm">
                <Badge>{run.status}</Badge>{' '}
                <span className="text-muted-foreground">
                  {new Date(run.created_at).toLocaleString()}
                </span>
                {run.error && (
                  <p className="mt-1" role="status">
                    {run.error}
                  </p>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            Queued requests are picked up by the worker within about a minute.
            You can leave this page while Pilot works.
          </p>
        </section>
      )}
      {!version ? (
        <section className={`${CARD} py-12 text-center`}>
          <h3 className="text-xl font-semibold">
            Start with your group’s context
          </h3>
          <p className="mt-2 text-muted-foreground">
            Save dates and a destination, then ask Pilot for a sourced draft or
            explore the Chicago sample.
          </p>
        </section>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              Plan version
              <select
                className={FIELD}
                value={version.id}
                onChange={(e) => {
                  setVersionId(e.target.value);

                  setDay('');
                }}
              >
                {data.versions.map((v, index) => (
                  <option key={v.id} value={v.id}>
                    {v.sample ? 'Sample: ' : ''}
                    {v.title} · {data.versions.length - index}
                    {v.id === data.selected_id ? ' · Selected' : ''}
                  </option>
                ))}
              </select>
            </label>
            {isOrganiser && !selected && (
              <Button
                disabled={action.isPending || !version.current}
                onClick={() =>
                  action.mutate(async () =>
                    unwrap(
                      await api.POST(
                        '/api/trips/{trip_id}/planning/versions/{version_id}/select',

                        {
                          params: {
                            path: { trip_id: tripId, version_id: version.id },
                          },
                        },
                      ),
                    ),
                  )
                }
              >
                {version.sample
                  ? 'Select sample for demo'
                  : 'Select this version'}
              </Button>
            )}
            {version.id === data.selected_id && <Badge>Selected plan</Badge>}
          </div>
          {version.sample && (
            <p
              role="note"
              className="rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm"
            >
              <strong>Illustrative Chicago sample.</strong> Costs are examples,
              not quotes. This fixture has not checked anyone’s private
              constraints. Only demo trips can select it.
            </p>
          )}
          {!version.current && (
            <p role="status" className="text-sm text-destructive">
              Trip context, membership or private inputs changed since this
              version was created. Keep it as history; generate a fresh draft
              before making decisions.
            </p>
          )}
          {data.my_explanations[version.id] && (
            <section
              className={CARD}
              aria-label="Your private plan explanation"
            >
              <h3 className="font-semibold">Why this fits you · private</h3>
              <p className="mt-2 whitespace-pre-wrap text-sm">
                {data.my_explanations[version.id]}
              </p>
            </section>
          )}
          <fieldset
            className="flex flex-wrap gap-2"
            aria-label="Itinerary days"
          >
            {days.map((value, index) => (
              <Button
                key={value}
                variant={value === activeDay ? 'default' : 'outline'}
                aria-pressed={value === activeDay}
                onClick={() => setDay(value)}
              >
                Day {index + 1} · {value}
              </Button>
            ))}
          </fieldset>
          <p className="text-xs text-muted-foreground">
            All times in {data.context.timezone}. USD estimates, not incurred
            costs or payment requests.
          </p>
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.85fr)]">
            <ol className="space-y-4">
              {items.map((item, index) => (
                <li key={item.id} className={CARD}>
                  <div className="flex justify-between gap-4">
                    <h3 className="font-semibold">
                      {index + 1}. {item.title}
                    </h3>
                    <span className="shrink-0 text-sm">
                      {item.starts_at.slice(0, 5)}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {item.location} · {item.duration_minutes} minutes
                  </p>
                  {item.evidence && (
                    <p className="mt-2 text-sm text-muted-foreground">
                      {item.evidence}
                    </p>
                  )}
                  <p className="mt-3 font-semibold">
                    {money(item.total_cents)}{' '}
                    <span className="text-xs font-normal text-muted-foreground">
                      group estimate
                    </span>
                  </p>
                  <ul className="mt-2 text-sm">
                    {Object.entries(version.shares[item.id] ?? {}).map(
                      ([member, cents]) => (
                        <li key={member}>
                          {memberName(member)}: {money(cents)}
                        </li>
                      ),
                    )}
                  </ul>
                  <ul className="mt-3 text-xs text-muted-foreground">
                    {item.sources.map((source) => (
                      <li key={source.url}>
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="underline"
                        >
                          {source.label}
                        </a>{' '}
                        · referenced {source.checked_at.slice(0, 10)}
                      </li>
                    ))}
                  </ul>
                  {version.id === selected?.id &&
                    me.data &&
                    item.participants.includes(me.data.id) && (
                      <Button
                        className="mt-3 mr-2"
                        variant="outline"
                        disabled={
                          action.isPending ||
                          !version.current ||
                          item.participants.length < 2
                        }
                        onClick={() =>
                          action.mutate(async () =>
                            unwrap(
                              await api.POST(
                                '/api/trips/{trip_id}/planning/proposals',
                                {
                                  params: { path: { trip_id: tripId } },

                                  body: {
                                    base_id: version.id,
                                    cancelled_item_id: item.id,
                                    opt_out: true,
                                  },
                                },
                              ),
                            ),
                          )
                        }
                      >
                        Propose my opt-out
                      </Button>
                    )}
                  {isOrganiser && version.id === selected?.id && (
                    <Button
                      className="mt-3"
                      variant="outline"
                      onClick={() => setCancelledId(item.id)}
                    >
                      Cancel / find alternatives
                    </Button>
                  )}
                </li>
              ))}
            </ol>
            <ItineraryMap key={`${version.id}-${activeDay}`} items={items} />
          </div>
          <section className={CARD} aria-label="Estimated budget">
            <h3 className="font-semibold">
              Estimated itinerary budget · {money(version.total_cents)} total
            </h3>
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {Object.entries(version.totals).map(([member, cents]) => (
                <li key={member} className="flex justify-between gap-3 text-sm">
                  <span>{memberName(member)}</span>
                  <strong>{money(cents)}</strong>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm">
              This day:{' '}
              {money(
                items.reduce((total, item) => total + item.total_cents, 0),
              )}{' '}
              group estimate.
            </p>
            {selected && selected.id !== version.id && (
              <p className="mt-2 text-sm">
                Compared with selected plan:{' '}
                {money(version.total_cents - selected.total_cents)} group
                estimate change;{' '}
                {
                  version.items.filter(
                    (item) =>
                      !selected.items.some(
                        (old) => JSON.stringify(old) === JSON.stringify(item),
                      ),
                  ).length
                }{' '}
                added or changed activities,{' '}
                {
                  selected.items.filter(
                    (item) =>
                      !version.items.some((current) => current.id === item.id),
                  ).length
                }{' '}
                removed.
              </p>
            )}
            <p className="mt-3 text-xs text-muted-foreground">
              Opt-out proposals keep the activity's group estimate fixed and
              redistribute its shares among remaining participants. Everyone
              affected must accept again. Exact cents reconcile across
              participants. This is an estimate; no funds have moved and no
              refunds are assumed.
            </p>
          </section>
        </>
      )}
      {cancelled && selected && (
        <section className={CARD} aria-label="Cancellation alternatives">
          <div className="flex justify-between gap-3">
            <h3 className="font-semibold">Replace {cancelled.title}</h3>
            <Button variant="ghost" onClick={() => setCancelledId('')}>
              Close
            </Button>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            The selected plan stays in place until affected members accept an
            alternative. Unrelated items keep their IDs and history.
          </p>
          {alternatives.length === 0 && (
            <p className="mt-3 text-sm">
              No saved alternatives for this day yet. Use Research alternatives
              to ask Pilot for sourced options.
            </p>
          )}
          <ul className="mt-4 space-y-3">
            {alternatives.map(({ version: candidate, item }) => (
              <li
                key={`${candidate.id}-${item.id}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
              >
                <span className="text-sm">
                  {item.title} · {money(item.total_cents)} estimate (
                  {money(item.total_cents - cancelled.total_cents)} group
                  difference)
                </span>
                <Button
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate(async () =>
                      unwrap(
                        await api.POST(
                          '/api/trips/{trip_id}/planning/proposals',

                          {
                            params: { path: { trip_id: tripId } },

                            body: {
                              base_id: selected.id,

                              cancelled_item_id: cancelled.id,

                              candidate_version_id: candidate.id,

                              candidate_item_id: item.id,
                              opt_out: false,
                            },
                          },
                        ),
                      ),
                    )
                  }
                >
                  Propose alternative
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.proposals.length > 0 && (
        <section className="space-y-4" aria-label="Plan change proposals">
          <h3 className="text-xl font-semibold">Proposed changes</h3>
          {data.proposals.map((proposal) => {
            const proposed = data.versions.find(
              (v) => v.id === proposal.version_id,
            );

            const stale =
              proposal.base_id !== data.selected_id || !proposed?.current;

            return (
              <article key={proposal.id} className={CARD}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h4 className="font-semibold">
                    {proposed?.title ?? 'Plan revision'}{' '}
                    <Badge>{proposal.status}</Badge>
                  </h4>
                  <Button
                    variant="outline"
                    onClick={() => setVersionId(proposal.version_id)}
                  >
                    Review revision
                  </Button>
                </div>
                <ul className="mt-3 space-y-1 text-sm">
                  {proposal.affected.map((id) => (
                    <li key={id}>
                      {memberName(id)} ·{' '}
                      {proposal.responses[id] ?? 'Awaiting response'} · estimate
                      change {money(proposal.cost_differences[id] ?? 0)}
                    </li>
                  ))}
                </ul>
                {proposal.status === 'open' && !stale && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {me.data &&
                      proposal.affected.includes(me.data.id) &&
                      (
                        ['accept', 'discuss', 'alternative', 'reject'] as const
                      ).map((response) => (
                        <Button
                          key={response}
                          variant={
                            response === 'accept' ? 'default' : 'outline'
                          }
                          disabled={action.isPending}
                          onClick={() =>
                            action.mutate(async () =>
                              unwrap(
                                await api.POST(
                                  '/api/trips/{trip_id}/planning/proposals/{proposal_id}/respond',

                                  {
                                    params: {
                                      path: {
                                        trip_id: tripId,

                                        proposal_id: proposal.id,
                                      },
                                    },

                                    body: {
                                      version_id: proposal.version_id,

                                      response,
                                    },
                                  },
                                ),
                              ),
                            )
                          }
                        >
                          {response === 'accept'
                            ? 'Accept this revision'
                            : response === 'discuss'
                              ? 'Needs discussion'
                              : response === 'alternative'
                                ? 'Request another alternative'
                                : 'Reject'}
                        </Button>
                      ))}
                    {isOrganiser && (
                      <Button
                        disabled={
                          action.isPending ||
                          proposal.affected.some(
                            (id) => proposal.responses[id] !== 'accept',
                          )
                        }
                        onClick={() =>
                          action.mutate(async () => {
                            const result = unwrap(
                              await api.POST(
                                '/api/trips/{trip_id}/planning/proposals/{proposal_id}/finalize',

                                {
                                  params: {
                                    path: {
                                      trip_id: tripId,

                                      proposal_id: proposal.id,
                                    },
                                  },
                                },
                              ),
                            );

                            setVersionId(proposal.version_id);

                            setCancelledId('');

                            return result;
                          })
                        }
                      >
                        Apply accepted revision
                      </Button>
                    )}
                  </div>
                )}
                {stale && proposal.status === 'open' && (
                  <p className="mt-3 text-sm text-muted-foreground">
                    This proposal is out of date. Create a new proposal from the
                    current selected plan.
                  </p>
                )}
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}

export function TripContextSummary({ tripId }: { tripId: string }) {
  const query = useQuery({
    queryKey: ['trip-planning', tripId],

    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}/planning', {
          params: { path: { trip_id: tripId } },
        }),
      ),
  });

  if (query.isPending) return <>Loading trip details…</>;

  if (query.isError) return <>Trip details could not be loaded.</>;

  const context = query.data.context;

  return (
    <>
      {context.destination || 'Destination to be decided'} ·{' '}
      {context.start_date ?? 'Dates to be decided'} — {context.end_date ?? ''} ·{' '}
      {context.timezone}
    </>
  );
}
