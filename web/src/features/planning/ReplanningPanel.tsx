import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useRef, useState } from 'react';
import { shownName } from '@/components/Avatar';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ApiError, api, unwrap } from '@/lib/api';
import type { components } from '@/lib/api-types';
import { budgetCents } from '../trips/TravelPreferencesPanel';

type Draft = components['schemas']['PlanVersionView'];
type Item = components['schemas']['PlanItem'];
type Proposal = components['schemas']['ProposalView'];
type Proposed = components['schemas']['ProposeReplacement'];
type Action = components['schemas']['ProposalResponse']['action'];
type Member = components['schemas']['MemberView'];
type Trip = components['schemas']['TripView'];

const ROUTE = '/api/trips/{trip_id}/replanning';
const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});
const amount = (cents: number | null) =>
  cents === null ? 'Estimate pending' : usd.format(cents / 100);
const message = (error: unknown) =>
  error instanceof ApiError && error.status !== 422
    ? error.message
    : 'Check the details and try again.';

function ReplacementForm({
  plan,
  members,
  busy,
  onPropose,
  onClose,
}: {
  plan: Draft;
  members: Member[];
  busy: boolean;
  onPropose: (body: Proposed) => void;
  onClose: () => void;
}) {
  const [id, setId] = useState(plan.items[0]?.id);
  const [validation, setValidation] = useState<string>();
  const attempt = useRef<{ payload: string; id: string } | null>(null);
  const item = plan.items.find((entry) => entry.id === id);
  if (!item) return null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!item || busy) return;
    const fields = new FormData(event.currentTarget);
    const title = String(fields.get('title') ?? '').trim();
    const participant_ids = fields.getAll('participants').map(String);
    if (!title || !participant_ids.length) {
      setValidation(
        'Enter an activity name and choose at least one participant.',
      );
      return;
    }
    let estimated_cents: number | null;
    try {
      estimated_cents = budgetCents(String(fields.get('estimate') ?? ''));
    } catch {
      setValidation(
        'Enter a USD estimate between $0 and $1,000,000 with up to two decimals.',
      );
      return;
    }
    setValidation(undefined);
    const body = {
      base_version: plan.version,
      replacement: {
        id: item.id,
        title,
        participant_ids,
        estimated_cents,
        day: String(fields.get('day') ?? ''),
        location: String(fields.get('location') ?? ''),
      },
    };
    const payload = JSON.stringify(body);
    if (attempt.current?.payload !== payload) {
      attempt.current = { payload, id: crypto.randomUUID() };
    }
    onPropose({ ...body, proposal_id: attempt.current.id });
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-xl border border-border p-4"
    >
      <fieldset disabled={busy} className="space-y-3">
        <div className="space-y-1">
          <label htmlFor="replace-activity">Activity to replace</label>
          <select
            id="replace-activity"
            className="block w-full rounded-lg border border-input bg-background p-2 text-sm"
            value={id}
            onChange={(event) => {
              setId(event.target.value);
              setValidation(undefined);
            }}
          >
            {plan.items.map((entry) => (
              <option value={entry.id} key={entry.id}>
                {entry.day} · {entry.title}
              </option>
            ))}
          </select>
        </div>
        <div key={item.id} className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="replace-title">Replacement activity</label>
            <Input
              id="replace-title"
              name="title"
              maxLength={120}
              required
              placeholder={item.title}
            />
          </div>
          <div>
            <label htmlFor="replace-day">Replacement date</label>
            <Input
              id="replace-day"
              name="day"
              type="date"
              defaultValue={item.day}
              required
            />
          </div>
          <div>
            <label htmlFor="replace-location">Replacement location</label>
            <Input id="replace-location" name="location" maxLength={160} />
          </div>
          <div>
            <label htmlFor="replace-estimate">Replacement estimate (USD)</label>
            <Input
              id="replace-estimate"
              name="estimate"
              inputMode="decimal"
              placeholder="Leave blank if unknown"
            />
          </div>
          <fieldset className="sm:col-span-2">
            <legend className="mb-1 text-sm font-medium">
              Replacement participants
            </legend>
            <div className="flex flex-wrap gap-3">
              {members.map((member) => (
                <label
                  className="flex items-center gap-1.5 text-sm"
                  key={member.account_id}
                >
                  <input
                    type="checkbox"
                    name="participants"
                    value={member.account_id}
                    defaultChecked={item.participant_ids.includes(
                      member.account_id,
                    )}
                  />
                  {shownName(member)}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit">
            {busy ? 'Saving…' : 'Send replacement proposal'}
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </fieldset>
      {validation && (
        <p role="alert" className="text-sm text-destructive">
          {validation}
        </p>
      )}
    </form>
  );
}

function ActivitySummary({ label, item }: { label: string; item: Item }) {
  return (
    <div className="rounded-lg bg-muted/60 p-3">
      <h4 className="text-xs font-semibold text-muted-foreground">{label}</h4>
      <p className="font-semibold break-words">{item.title}</p>
      <p className="text-sm text-muted-foreground">
        <time dateTime={item.day}>{item.day}</time>
        {item.location && ` · ${item.location}`}
      </p>
      <p className="text-sm">{amount(item.estimated_cents)}</p>
    </div>
  );
}

function ProposalDetails({
  proposal,
  members,
  viewerId,
  organiser,
  busy,
  onRespond,
}: {
  proposal: Proposal;
  members: Member[];
  viewerId?: string;
  organiser: boolean;
  busy: boolean;
  onRespond: (action: Action) => void;
}) {
  const { original, replacement, affected_ids, accepted_ids, opted_out_ids } =
    proposal;
  const open = proposal.state === 'open';
  const noParticipants = replacement.participant_ids.every((id) =>
    opted_out_ids.includes(id),
  );
  const affected = viewerId !== undefined && affected_ids.includes(viewerId);
  const accepted = viewerId !== undefined && accepted_ids.includes(viewerId);
  const memberIds = new Set([
    ...original.participant_ids,
    ...replacement.participant_ids,
    ...opted_out_ids,
  ]);
  const hasDeparture = affected_ids.some(
    (id) => !members.some((member) => member.account_id === id),
  );

  return (
    <section className="space-y-3" aria-label="Activity replacement proposal">
      <h4 className="font-semibold">
        Replacement revision {proposal.revision}
        {proposal.state === 'applied' &&
          ` · Applied to plan v${proposal.applied_version}`}
        {proposal.state === 'withdrawn' &&
          (noParticipants
            ? ' · Withdrawn after the last participant opted out'
            : ' · Withdrawn')}
      </h4>
      {open && (
        <p role="status" className="text-sm text-muted-foreground">
          {accepted_ids.length} of {affected_ids.length} affected members
          accepted.
          {proposal.revision > 1 &&
            ' Shares were recalculated. This revision needs fresh acceptance.'}
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        <ActivitySummary
          label="Current activity before this change"
          item={original}
        />
        <ActivitySummary label="Replacement activity" item={replacement} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">
            Estimated activity shares in USD
          </caption>
          <thead className="text-muted-foreground">
            <tr>
              <th scope="col" className="p-2">
                Member
              </th>
              <th scope="col" className="p-2">
                Before
              </th>
              <th scope="col" className="p-2">
                After
              </th>
              <th scope="col" className="p-2">
                Response
              </th>
            </tr>
          </thead>
          <tbody>
            {[...memberIds].map((id) => {
              const before = original.shares.find(
                (share) => share.account_id === id,
              );
              const after = opted_out_ids.includes(id)
                ? undefined
                : replacement.shares.find((share) => share.account_id === id);
              const member = members.find((entry) => entry.account_id === id);
              return (
                <tr key={id} className="border-t border-border">
                  <th scope="row" className="p-2 font-medium">
                    {after?.name ??
                      before?.name ??
                      (member ? shownName(member) : 'Former member')}
                  </th>
                  <td className="p-2">
                    {before ? amount(before.cents) : 'Excluded'}
                  </td>
                  <td className="p-2">
                    {after ? amount(after.cents) : 'Excluded'}
                  </td>
                  <td className="p-2">
                    {opted_out_ids.includes(id)
                      ? 'Opted out'
                      : accepted_ids.includes(id)
                        ? 'Accepted'
                        : open && affected_ids.includes(id)
                          ? 'Awaiting'
                          : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {open && hasDeparture && (
        <p className="text-sm text-destructive">
          Membership changed. The organiser can withdraw and send a new
          proposal.
        </p>
      )}
      {open && (
        <div className="flex flex-wrap gap-2">
          {affected && !accepted && (
            <Button
              type="button"
              disabled={busy || hasDeparture}
              onClick={() => onRespond('accept')}
            >
              Accept revision
            </Button>
          )}
          {affected &&
            viewerId &&
            replacement.participant_ids.includes(viewerId) && (
              <Button
                type="button"
                variant="outline"
                disabled={busy || hasDeparture}
                onClick={() => onRespond('opt_out')}
              >
                Opt out of activity
              </Button>
            )}
          {organiser && (
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => onRespond('withdraw')}
            >
              Withdraw proposal
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

export function ReplanningPanel({
  tripId,
  viewed,
  currentVersion,
  members,
  viewerId,
  organiser,
  onOpen,
}: {
  tripId: string;
  viewed: Draft | null;
  currentVersion: number | null;
  members: Member[];
  viewerId?: string | undefined;
  organiser: boolean;
  onOpen: (version: number) => void;
}) {
  const client = useQueryClient();
  const [composing, setComposing] = useState(false);
  const params = { path: { trip_id: tripId } };
  const queryKey = ['trip-replanning', tripId];
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) =>
      unwrap(await api.GET(ROUTE, { params, signal })),
    retry: false,
  });
  const refresh = () => void client.invalidateQueries({ queryKey });
  const setCurrent = (version: number) => {
    client.setQueryData<Trip>(
      ['trip', tripId],
      (trip) => trip && { ...trip, current_plan_version: version },
    );
    void client.invalidateQueries({ queryKey: ['trip', tripId], exact: true });
  };
  const choose = useMutation({
    mutationFn: async (version: number) =>
      unwrap(
        await api.PUT('/api/trips/{trip_id}/replanning/current', {
          params,
          body: { version },
        }),
      ),
    onSuccess: (result) => setCurrent(result.version),
  });
  const propose = useMutation({
    mutationFn: async (body: Proposed) =>
      unwrap(
        await api.POST('/api/trips/{trip_id}/replanning/proposals', {
          params,
          body,
        }),
      ),
    onSuccess: () => {
      setComposing(false);
      refresh();
    },
  });
  const respond = useMutation({
    mutationFn: async ({
      proposal,
      action,
    }: {
      proposal: Proposal;
      action: Action;
    }) =>
      unwrap(
        await api.POST(
          '/api/trips/{trip_id}/replanning/proposals/{proposal_id}/respond',
          {
            params: {
              path: { trip_id: tripId, proposal_id: proposal.proposal_id },
            },
            body: { revision: proposal.revision, action },
          },
        ),
      ),
    onSuccess: (result) => {
      refresh();
      if (result.applied_version !== null) {
        setCurrent(result.applied_version);
        void client.invalidateQueries({
          queryKey: ['trip-plan', tripId, 'latest'],
        });
        onOpen(result.applied_version);
      }
    },
    onError: refresh,
  });
  const proposal = query.data?.proposal;
  const canPropose =
    organiser &&
    !query.isPending &&
    !query.isError &&
    proposal?.state !== 'open' &&
    viewed !== null &&
    viewed.version === currentVersion &&
    viewed.items.length > 0;
  const error = respond.error ?? propose.error ?? choose.error;

  return (
    <Card>
      <CardHeader>
        <h3 className="font-semibold">Current plan & replacements</h3>
        <p className="text-sm text-muted-foreground">
          {currentVersion === null
            ? 'Select an itinerary to start proposing changes.'
            : `Current plan v${currentVersion}`}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {organiser &&
            currentVersion === null &&
            viewed &&
            viewed.items.length > 0 && (
              <Button
                type="button"
                disabled={choose.isPending}
                onClick={() => choose.mutate(viewed.version)}
              >
                Set as current plan
              </Button>
            )}
          {currentVersion !== null && viewed?.version !== currentVersion && (
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpen(currentVersion)}
            >
              Open current plan v{currentVersion}
            </Button>
          )}
          {canPropose && !composing && (
            <Button
              type="button"
              onClick={() => {
                propose.reset();
                respond.reset();
                setComposing(true);
              }}
            >
              Propose activity replacement
            </Button>
          )}
        </div>
        {composing && canPropose && (
          <ReplacementForm
            plan={viewed}
            members={members}
            busy={propose.isPending}
            onPropose={propose.mutate}
            onClose={() => setComposing(false)}
          />
        )}
        {proposal && (
          <ProposalDetails
            proposal={proposal}
            members={members}
            viewerId={viewerId}
            organiser={organiser}
            busy={respond.isPending}
            onRespond={(action) => respond.mutate({ proposal, action })}
          />
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {message(error)}
          </p>
        )}
        {query.isError && (
          <Button
            type="button"
            variant="outline"
            onClick={() => void query.refetch()}
          >
            Retry loading replacement status
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
