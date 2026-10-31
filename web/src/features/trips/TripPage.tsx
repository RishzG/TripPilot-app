import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Avatar, shownName } from '@/components/Avatar';
import { EmptyState } from '@/components/EmptyState';
import { ErrorRetry } from '@/components/ErrorRetry';
import { InviteLinkCard } from '@/components/InviteLinkCard';
import { SkeletonList } from '@/components/SkeletonList';
import { Alert, AlertAction } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/utils';
import { api, unwrap } from '../../lib/api';
import type { components } from '../../lib/api-types';
import { useMe } from '../auth/useMe';
import { SavePayPalButton } from '../paypal/SavePayPalButton';
import { useTripEvents } from './useTripEvents';

type TripData = components['schemas']['TripView'];
type MemberData = components['schemas']['MemberView'];

const MAX_MEMBERS = 12;
const CONFIRM_REVERT_MS = 6000;
const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

const PAGE = 'mx-auto w-full max-w-md p-4 pt-6 md:max-w-5xl md:p-8';
const HEADING = 'text-xl font-semibold leading-[1.2]';

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

const DISMISSED_KEY_PREFIX = 'tp-save-banner-dismissed:';

function bannerDismissed(tripId: string): boolean {
  try {
    return localStorage.getItem(`${DISMISSED_KEY_PREFIX}${tripId}`) !== null;
  } catch {
    return false;
  }
}

/**
 * The quiet reminder for a member who skipped saving PayPal (D-06): one dismissible banner with the
 * save control, never an email. It needs the member's OWN saved status from the vault status
 * endpoint (D-08); nobody else's status is requested or shown. It is hidden when PayPal is saved,
 * when the status cannot be read, for demo personas (their PayPal comes from the buyer pool) and
 * after Dismiss, which is remembered per trip in localStorage.
 */
function SaveBanner({
  tripId,
  className,
}: {
  tripId: string;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const me = useMe();
  const [dismissed, setDismissed] = useState(() => bannerDismissed(tripId));
  const [failed, setFailed] = useState(false);
  const isMember = me.data?.kind === 'member' && !me.data.is_persona;
  const status = useQuery({
    queryKey: ['vault-status'],
    queryFn: async () => unwrap(await api.GET('/api/paypal/vault/status')),
    enabled: isMember,
    retry: false,
  });

  if (!isMember || dismissed || status.data?.saved !== false) {
    return null;
  }

  function dismiss() {
    try {
      localStorage.setItem(`${DISMISSED_KEY_PREFIX}${tripId}`, '1');
    } catch {
      // Private mode: the banner is hidden for this visit only.
    }
    setDismissed(true);
  }

  // A quiet reminder, not an emergency: a named region rather than the Alert default role=alert.
  return (
    <Alert
      variant="money"
      role="region"
      aria-label="Save PayPal"
      className={className}
    >
      <p className="text-base">Save PayPal so you can commit in one tap</p>
      <AlertAction className="top-0 right-0">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Dismiss"
          onClick={dismiss}
        >
          <X aria-hidden="true" />
        </Button>
      </AlertAction>
      <div className="mt-2">
        <SavePayPalButton
          setupTokenPath="/api/paypal/vault/setup-token"
          paymentTokenPath="/api/paypal/vault/payment-token"
          onSaved={() => {
            setFailed(false);
            void queryClient.invalidateQueries({ queryKey: ['vault-status'] });
          }}
          onFailed={() => setFailed(true)}
        />
      </div>
      {failed && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {SUBMIT_FAILED_MESSAGE}
        </p>
      )}
    </Alert>
  );
}

/**
 * The organiser's invite card: fetches the link, owns the reset and open/close requests, and
 * renders the shared `InviteLinkCard` (copy, two-step reset, joining toggle and their motion).
 */
function InviteCard({
  tripId,
  joiningClosed,
  patchTrip,
  animateEntrance,
}: {
  tripId: string;
  joiningClosed: boolean;
  patchTrip: (update: (trip: TripData) => TripData) => void;
  animateEntrance: boolean;
}) {
  const queryClient = useQueryClient();
  const [failed, setFailed] = useState(false);
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
      setFailed(false);
      queryClient.setQueryData(['invite-link', tripId], data);
    },
    onError: () => setFailed(true),
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
      setFailed(false);
      patchTrip((trip) => ({ ...trip, joining_closed }));
    },
    onError: () => setFailed(true),
  });

  return (
    <InviteLinkCard
      url={link.data?.url}
      joiningClosed={joiningClosed}
      loadFailed={link.isError}
      onRetry={() => void link.refetch()}
      onResetLink={() => resetLink.mutate()}
      resetPending={resetLink.isPending}
      onToggleJoining={() => toggleJoining.mutate(!joiningClosed)}
      togglePending={toggleJoining.isPending}
      actionFailed={failed}
      animateEntrance={animateEntrance}
    />
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
              .map((member) => `${shownName(member)} joined the trip`)
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
      className={cn(
        'flex min-h-14 flex-wrap items-center gap-3 px-(--card-spacing) py-2',
        entering && ENTERING_ROW,
      )}
    >
      <Avatar
        name={shownName(member)}
        kind={member.avatar_kind}
        avatarKey={member.avatar_key}
      />
      <span
        title={shownName(member)}
        className="min-w-0 flex-1 truncate text-base font-semibold"
      >
        {shownName(member)}
      </span>
      {member.role === 'organiser' && <Badge>Organiser</Badge>}
      {canRemove &&
        member.role !== 'organiser' &&
        (confirming ? (
          <span className="flex w-full flex-wrap items-center gap-2">
            <span className="text-sm">Remove {shownName(member)}?</span>
            <Button
              type="button"
              variant="destructive"
              disabled={removing}
              aria-busy={removing}
              onClick={() => onRemove(member.account_id)}
            >
              {removing && <Spinner />}
              Yes, remove
            </Button>
            <Button type="button" variant="ghost" onClick={onDisarm}>
              Keep {shownName(member)}
            </Button>
          </span>
        ) : (
          <Button
            type="button"
            variant="ghost"
            aria-label={`Remove ${shownName(member)}`}
            onClick={() => onArm(member.account_id)}
          >
            Remove
          </Button>
        ))}
    </li>
  );
}

function TripContent({
  trip,
  tripId,
  animateInvite,
}: {
  trip: TripData;
  tripId: string;
  animateInvite: boolean;
}) {
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
      setLastRemoved(shownName(gone));
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
  // Phone: one column in the UI-SPEC order (header, save banner, invite card, members, plan
  // placeholder, Leave). From md: a two-pane grid. The panes are `contents` on a phone so the
  // `order-*` classes arrange their children in one column, and real flex columns from md, where
  // each pane keeps its own DOM order (header first for screen readers) and `md:order-none` resets.
  return (
    <div className={PAGE}>
      <div className="flex flex-col gap-6 md:grid md:grid-cols-[320px_1fr] md:items-start md:gap-8">
        <div className="contents md:col-start-2 md:row-start-1 md:flex md:flex-col md:gap-6">
          <div className="order-1 md:order-none">
            <h1 className="text-balance break-words text-display font-semibold leading-[1.2]">
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
          </div>
          <SaveBanner tripId={tripId} className="order-2 md:order-none" />
          <Card className="order-5 border-dashed text-muted-foreground md:order-none">
            <CardContent>
              <p>Your plan will appear here once the group starts planning</p>
              <p className="mt-1">Nobody pays anything yet.</p>
            </CardContent>
          </Card>
        </div>
        <div className="contents md:sticky md:top-[88px] md:col-start-1 md:row-start-1 md:flex md:flex-col md:gap-6">
          {isOrganiser && (
            <div className="order-3 md:order-none">
              <InviteCard
                tripId={tripId}
                joiningClosed={trip.joining_closed}
                patchTrip={patchTrip}
                animateEntrance={animateInvite}
              />
            </div>
          )}
          <Card className="order-4 md:order-none">
            <CardHeader>
              <h2 id="whos-in" className={HEADING}>
                Who's in
              </h2>
            </CardHeader>
            <div aria-live="polite" className="sr-only">
              {announcement}
            </div>
            <ul aria-labelledby="whos-in" className="divide-y divide-border">
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
            {(lastRemoved !== null || members.length === 1) && (
              <CardContent className="flex flex-col gap-4">
                {lastRemoved !== null && (
                  <p className="text-sm text-muted-foreground">
                    {lastRemoved} can't rejoin from the invite link unless you
                    add them back.
                  </p>
                )}
                {members.length === 1 && (
                  <EmptyState
                    as="h3"
                    title="Just you so far. Send the invite!"
                    description="Copy the invite and drop it in your group chat."
                  />
                )}
              </CardContent>
            )}
          </Card>
          {isOrganiser && removed.length > 0 && (
            <Card className="order-4 md:order-none">
              <CardHeader>
                <h2 id="removed" className={HEADING}>
                  Removed
                </h2>
              </CardHeader>
              <ul aria-labelledby="removed" className="divide-y divide-border">
                {removed.map((person) => (
                  <li
                    key={person.account_id}
                    className="flex min-h-14 items-center gap-3 px-(--card-spacing) py-2"
                  >
                    <Avatar
                      name={person.display_name}
                      kind="initials"
                      avatarKey={null}
                    />
                    <span
                      id={`removed-${person.account_id}`}
                      title={person.display_name}
                      className="min-w-0 flex-1 truncate text-base font-semibold"
                    >
                      {person.display_name}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      aria-describedby={`removed-${person.account_id}`}
                      disabled={readdMember.isPending}
                      onClick={() => readdMember.mutate(person.account_id)}
                    >
                      Add back
                    </Button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {!isOrganiser && (
            <div className="order-6 md:order-none">
              {leave.armed === null ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => leave.arm(true)}
                >
                  Leave trip
                </Button>
              ) : (
                <div className="flex flex-col gap-2">
                  <p className="text-base font-semibold">Leave {name}?</p>
                  <p className="text-sm text-muted-foreground">
                    You'll need a new invite to come back.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="destructive"
                      disabled={leaveTrip.isPending}
                      aria-busy={leaveTrip.isPending}
                      onClick={() => leaveTrip.mutate()}
                    >
                      {leaveTrip.isPending && <Spinner />}
                      Leave trip
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={leave.disarm}
                    >
                      Stay in trip
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
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
  const queryClient = useQueryClient();
  // The invite card plays its entrance only when the trip was not already on screen from cache.
  const [cachedAtMount] = useState(
    () => queryClient.getQueryData(['trip', tripId]) !== undefined,
  );
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
      <div className={PAGE}>
        <SkeletonList withTitle />
      </div>
    );
  }

  if (trip.isError) {
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <ErrorRetry onRetry={() => void trip.refetch()} />
      </div>
    );
  }

  return (
    <TripContent
      trip={trip.data}
      tripId={tripId}
      animateInvite={!cachedAtMount}
    />
  );
}
