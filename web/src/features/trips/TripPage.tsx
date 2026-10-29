import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { toast } from 'sonner';
import { api, unwrap } from '../../lib/api';
import type { components } from '../../lib/api-types';
import { useTripEvents } from './useTripEvents';

type TripData = components['schemas']['TripView'];
type MemberData = components['schemas']['MemberView'];

const MAX_MEMBERS = 12;
const CONFIRM_REVERT_MS = 6000;
const COPIED_ICON_MS = 2000;
const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

const PRIMARY_BUTTON =
  'inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground disabled:opacity-50';
const OUTLINE_BUTTON =
  'inline-flex min-h-11 items-center justify-center rounded-lg border border-border px-4 text-base font-semibold disabled:opacity-50';
const DANGER_BUTTON =
  'inline-flex min-h-11 items-center justify-center rounded-lg border border-destructive px-4 text-base font-semibold text-destructive disabled:opacity-50';
const QUIET_BUTTON =
  'inline-flex min-h-11 items-center justify-center rounded-lg px-4 text-base font-semibold disabled:opacity-50';

/** A two-step confirm that puts itself back after a few seconds (UI-SPEC, no dialog). */
function useArmed<T>() {
  const [armed, setArmed] = useState<T | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  function disarm() {
    clearTimeout(timer.current);
    setArmed(null);
  }
  function arm(value: T) {
    clearTimeout(timer.current);
    setArmed(value);
    timer.current = setTimeout(() => setArmed(null), CONFIRM_REVERT_MS);
  }
  useEffect(() => () => clearTimeout(timer.current), []);
  return { armed, arm, disarm };
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter((part) => part.length > 0)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('');
}

function Initials({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold"
    >
      {initialsOf(name)}
    </span>
  );
}

function InviteCard({
  tripId,
  joiningClosed,
  onError,
  patchTrip,
}: {
  tripId: string;
  joiningClosed: boolean;
  onError: (failed: boolean) => void;
  patchTrip: (update: (trip: TripData) => TripData) => void;
}) {
  const queryClient = useQueryClient();
  const field = useRef<HTMLInputElement>(null);
  const reset = useArmed<true>();
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const path = { params: { path: { trip_id: tripId } } };

  const link = useQuery({
    queryKey: ['invite-link', tripId],
    queryFn: async () =>
      unwrap(await api.GET('/api/trips/{trip_id}/invite', path)),
    retry: false,
  });
  const resetLink = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/trips/{trip_id}/invite/reset', path)),
    onSuccess: (data) => {
      onError(false);
      queryClient.setQueryData(['invite-link', tripId], data);
      reset.disarm();
    },
    onError: () => onError(true),
  });
  const toggleJoining = useMutation({
    mutationFn: async (closed: boolean) =>
      unwrap(
        await api.POST('/api/trips/{trip_id}/joining', {
          ...path,
          body: { closed },
        }),
      ),
    onSuccess: ({ joining_closed }) => {
      onError(false);
      patchTrip((trip) => ({ ...trip, joining_closed }));
    },
    onError: () => onError(true),
  });

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = setTimeout(() => setCopied(false), COPIED_ICON_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    const url = link.data?.url;
    if (url === undefined) {
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopyFailed(false);
      setCopied(true);
      toast('Copy the invite and drop it in your group chat');
    } catch {
      setCopyFailed(true);
      field.current?.select();
    }
  }

  const CopyIcon = copied ? Check : Copy;
  return (
    <section className="rounded-xl border border-border p-4">
      <h2 className="text-xl font-semibold leading-[1.2]">Invite link</h2>
      {link.isError ? (
        <div className="mt-4">
          <p className="text-muted-foreground">We couldn't load that.</p>
          <button
            type="button"
            onClick={() => link.refetch()}
            className={`mt-2 ${OUTLINE_BUTTON}`}
          >
            Retry loading
          </button>
        </div>
      ) : (
        <>
          <input
            ref={field}
            type="text"
            readOnly
            aria-label="Invite link address"
            value={link.data?.url ?? ''}
            className="mt-4 min-h-11 w-full truncate rounded-lg border border-muted-foreground bg-background px-4 text-base"
          />
          {copyFailed && (
            <p className="mt-2 text-sm text-muted-foreground">
              Press and hold to copy the link.
            </p>
          )}
          <button
            type="button"
            disabled={link.data === undefined}
            onClick={copy}
            className={`mt-4 ${PRIMARY_BUTTON}`}
          >
            <CopyIcon aria-hidden="true" size={20} />
            Copy invite link
          </button>
        </>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {reset.armed === null ? (
          <button
            type="button"
            onClick={() => reset.arm(true)}
            className={OUTLINE_BUTTON}
          >
            Reset link
          </button>
        ) : (
          <div className="flex w-full flex-col gap-2">
            <p className="text-sm">
              Reset? The old link stops working right away.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={resetLink.isPending}
                onClick={() => resetLink.mutate()}
                className={DANGER_BUTTON}
              >
                Yes, reset
              </button>
              <button
                type="button"
                onClick={reset.disarm}
                className={QUIET_BUTTON}
              >
                Keep old link
              </button>
            </div>
          </div>
        )}
        <button
          type="button"
          disabled={toggleJoining.isPending}
          onClick={() => toggleJoining.mutate(!joiningClosed)}
          className={OUTLINE_BUTTON}
        >
          {joiningClosed ? 'Open joining' : 'Close joining'}
        </button>
      </div>
      {joiningClosed && (
        <p className="mt-2 text-sm text-muted-foreground">
          Joining is closed. Nobody new can use the link.
        </p>
      )}
    </section>
  );
}

/**
 * Who arrived after the first paint (D-24): their rows animate in once and a screen reader hears
 * `<Name> joined the trip`. Rows present on first paint never animate. Uses the render-phase state
 * adjustment React recommends, so a new row's very first commit already carries its entrance.
 */
function useArrivals(members: MemberData[]): {
  entered: ReadonlySet<string>;
  announcement: string;
} {
  const current = new Set(members.map((member) => member.account_id));
  const [state, setState] = useState({
    seen: current,
    entered: new Set<string>() as ReadonlySet<string>,
    announcement: '',
  });
  const arrived = members.filter(
    (member) => !state.seen.has(member.account_id),
  );
  const departed = [...state.seen].some((id) => !current.has(id));
  if (arrived.length > 0 || departed) {
    setState({
      seen: current,
      entered: new Set(
        [
          ...state.entered,
          ...arrived.map((member) => member.account_id),
        ].filter((id) => current.has(id)),
      ),
      announcement:
        arrived.length > 0
          ? arrived
              .map((member) => `${member.display_name} joined the trip`)
              .join('. ')
          : state.announcement,
    });
  }
  return { entered: state.entered, announcement: state.announcement };
}

const ENTERING_ROW =
  'motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2';

function MemberRow({
  member,
  entering,
  canRemove,
  armedId,
  onArm,
  onDisarm,
  onRemove,
  removing,
}: {
  member: MemberData;
  entering: boolean;
  canRemove: boolean;
  armedId: string | null;
  onArm: (accountId: string) => void;
  onDisarm: () => void;
  onRemove: (accountId: string) => void;
  removing: boolean;
}) {
  const confirming = armedId === member.account_id;
  return (
    <li
      className={`flex min-h-14 flex-wrap items-center gap-3 px-4 py-2 ${entering ? ENTERING_ROW : ''}`}
    >
      <Initials name={member.display_name} />
      <span className="min-w-0 flex-1 truncate text-base font-semibold">
        {member.display_name}
      </span>
      {member.role === 'organiser' && (
        <span className="rounded-lg border border-border bg-muted px-2 text-sm font-semibold">
          Organiser
        </span>
      )}
      {canRemove &&
        member.role !== 'organiser' &&
        (confirming ? (
          <span className="flex w-full flex-wrap items-center gap-2">
            <span className="text-sm">Remove {member.display_name}?</span>
            <button
              type="button"
              disabled={removing}
              onClick={() => onRemove(member.account_id)}
              className={DANGER_BUTTON}
            >
              Yes, remove
            </button>
            <button type="button" onClick={onDisarm} className={QUIET_BUTTON}>
              Keep {member.display_name}
            </button>
          </span>
        ) : (
          <button
            type="button"
            aria-label={`Remove ${member.display_name}`}
            onClick={() => onArm(member.account_id)}
            className={QUIET_BUTTON}
          >
            Remove
          </button>
        ))}
    </li>
  );
}

function TripContent({ trip, tripId }: { trip: TripData; tripId: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const remove = useArmed<string>();
  const leave = useArmed<true>();
  const [failed, setFailed] = useState(false);
  const [lastRemoved, setLastRemoved] = useState<string | null>(null);
  const { entered, announcement } = useArrivals(trip.members);

  function patchTrip(update: (current: TripData) => TripData) {
    queryClient.setQueryData<TripData>(['trip', tripId], (current) =>
      current === undefined ? current : update(current),
    );
  }
  const memberPath = (accountId: string) => ({
    params: { path: { trip_id: tripId, account_id: accountId } },
  });

  const removeMember = useMutation({
    mutationFn: async (accountId: string) =>
      unwrap(
        await api.POST(
          '/api/trips/{trip_id}/members/{account_id}/remove',
          memberPath(accountId),
        ),
      ),
    onSuccess: ({ account_id }) => {
      setFailed(false);
      remove.disarm();
      const gone = trip.members.find((m) => m.account_id === account_id);
      if (gone === undefined) {
        return;
      }
      setLastRemoved(gone.display_name);
      patchTrip((current) => ({
        ...current,
        members: current.members.filter((m) => m.account_id !== account_id),
        removed_members: [
          ...(current.removed_members ?? []),
          { account_id, display_name: gone.display_name },
        ],
      }));
    },
    onError: () => setFailed(true),
  });
  const readdMember = useMutation({
    mutationFn: async (accountId: string) =>
      unwrap(
        await api.POST(
          '/api/trips/{trip_id}/members/{account_id}/readd',
          memberPath(accountId),
        ),
      ),
    onSuccess: ({ account_id }) => {
      setFailed(false);
      setLastRemoved(null);
      patchTrip((current) => {
        const back = (current.removed_members ?? []).find(
          (m) => m.account_id === account_id,
        );
        if (back === undefined) {
          return current;
        }
        return {
          ...current,
          members: [
            ...current.members,
            {
              account_id,
              display_name: back.display_name,
              nickname: null,
              avatar_kind: 'initials',
              avatar_key: null,
              role: 'member',
            },
          ],
          removed_members: (current.removed_members ?? []).filter(
            (m) => m.account_id !== account_id,
          ),
        };
      });
    },
    onError: () => setFailed(true),
  });
  const leaveTrip = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/trips/{trip_id}/leave', {
          params: { path: { trip_id: tripId } },
        }),
      ),
    onSuccess: () => {
      navigate('/');
      queryClient.removeQueries({ queryKey: ['trips'] });
      queryClient.removeQueries({ queryKey: ['trip', tripId], exact: true });
    },
    onError: () => setFailed(true),
  });

  const { name, members, is_organiser: isOrganiser } = trip;
  const removed = trip.removed_members ?? [];
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        {name}
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {members.length} of {MAX_MEMBERS} in
      </p>
      {failed && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {SUBMIT_FAILED_MESSAGE}
        </p>
      )}
      {isOrganiser && (
        <div className="mt-6">
          <InviteCard
            tripId={tripId}
            joiningClosed={trip.joining_closed}
            onError={setFailed}
            patchTrip={patchTrip}
          />
        </div>
      )}
      <h2 id="whos-in" className="mt-6 text-xl font-semibold leading-[1.2]">
        Who's in
      </h2>
      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <ul
        aria-labelledby="whos-in"
        className="mt-4 divide-y divide-border rounded-xl border border-border"
      >
        {members.map((member) => (
          <MemberRow
            key={member.account_id}
            member={member}
            entering={entered.has(member.account_id)}
            canRemove={isOrganiser}
            armedId={remove.armed}
            onArm={remove.arm}
            onDisarm={remove.disarm}
            onRemove={(accountId) => removeMember.mutate(accountId)}
            removing={removeMember.isPending}
          />
        ))}
      </ul>
      {lastRemoved !== null && (
        <p className="mt-2 text-sm text-muted-foreground">
          {lastRemoved} can't rejoin from the invite link unless you add them
          back.
        </p>
      )}
      {members.length === 1 && (
        <div className="mt-4">
          <h3 className="text-base font-semibold">
            Just you so far. Send the invite!
          </h3>
          <p className="mt-1 text-muted-foreground">
            Copy the invite and drop it in your group chat.
          </p>
        </div>
      )}
      {isOrganiser && removed.length > 0 && (
        <>
          <h2 id="removed" className="mt-6 text-xl font-semibold leading-[1.2]">
            Removed
          </h2>
          <ul
            aria-labelledby="removed"
            className="mt-4 divide-y divide-border rounded-xl border border-border"
          >
            {removed.map((person) => (
              <li
                key={person.account_id}
                className="flex min-h-14 items-center gap-3 px-4 py-2"
              >
                <Initials name={person.display_name} />
                <span
                  id={`removed-${person.account_id}`}
                  className="min-w-0 flex-1 truncate text-base font-semibold"
                >
                  {person.display_name}
                </span>
                <button
                  type="button"
                  aria-describedby={`removed-${person.account_id}`}
                  disabled={readdMember.isPending}
                  onClick={() => readdMember.mutate(person.account_id)}
                  className={OUTLINE_BUTTON}
                >
                  Add back
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="mt-6 rounded-xl border border-dashed border-border p-4 text-muted-foreground">
        <p>Your plan will appear here once the group starts planning</p>
        <p className="mt-1">Nobody pays anything yet.</p>
      </div>
      {!isOrganiser && (
        <div className="mt-6">
          {leave.armed === null ? (
            <button
              type="button"
              onClick={() => leave.arm(true)}
              className={QUIET_BUTTON}
            >
              Leave trip
            </button>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-base font-semibold">Leave {name}?</p>
              <p className="text-sm text-muted-foreground">
                You'll need a new invite to come back.
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={leaveTrip.isPending}
                  onClick={() => leaveTrip.mutate()}
                  className={DANGER_BUTTON}
                >
                  Leave trip
                </button>
                <button
                  type="button"
                  onClick={leave.disarm}
                  className={QUIET_BUTTON}
                >
                  Stay in trip
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The trip page (D-24): name, who is in, the organiser's invite link and membership controls.
 * It stays live: the trip event stream refetches the trip when anyone joins, leaves or is
 * removed, and each action also updates the lists from its own answer.
 */
export function TripPage() {
  const { tripId = '' } = useParams();
  useTripEvents(tripId);
  const trip = useQuery({
    queryKey: ['trip', tripId],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}', {
          params: { path: { trip_id: tripId } },
        }),
      ),
    retry: false,
  });

  if (trip.isPending) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
        <p className="text-muted-foreground">Loading your trip</p>
      </div>
    );
  }

  if (trip.isError) {
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <h1 className="text-xl font-semibold leading-[1.2]">
          We couldn't load that.
        </h1>
        <p className="mt-2 text-muted-foreground">
          Check your connection and try again.
        </p>
        <button
          type="button"
          onClick={() => trip.refetch()}
          className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
        >
          Retry loading
        </button>
      </div>
    );
  }

  return <TripContent trip={trip.data} tripId={tripId} />;
}
