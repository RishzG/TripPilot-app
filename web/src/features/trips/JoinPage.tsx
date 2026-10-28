import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, Navigate, useParams } from 'react-router';
import { ApiError, api, unwrap } from '../../lib/api';
import { useMe } from '../auth/useMe';

const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

const REFUSALS: Record<string, { heading: string; body: string }> = {
  removed: {
    heading: "You can't join this trip",
    body: 'The organiser removed you from this trip. Ask them to add you back.',
  },
  full: {
    heading: 'This trip is full',
    body: 'It already has 12 people.',
  },
  closed: {
    heading: 'Joining is closed',
    body: 'Ask the organiser to open it again.',
  },
};

const BAD_LINK = {
  heading: "This invite link isn't working",
  body: 'It may have been reset. Ask the organiser for a new one.',
};

const BUTTON_CLASS =
  'inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground disabled:opacity-50';
const QUIET_CLASS =
  'inline-flex min-h-11 w-full items-center justify-center rounded-lg px-4 text-base font-semibold';

function Notice({ heading, body }: { heading: string; body: string }) {
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-xl font-semibold leading-[1.2]">{heading}</h1>
      <p className="mt-2 text-muted-foreground">{body}</p>
    </div>
  );
}

function Loading() {
  return (
    <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
      <p className="text-muted-foreground">Loading the invite</p>
    </div>
  );
}

/** The join page for an invite link (D-23): a confirm card for a signed-in non-member. */
export function JoinPage() {
  const { token = '' } = useParams();
  const me = useMe();
  const signedIn = me.isSuccess && me.data !== null;
  const signedOut = me.isSuccess && me.data === null;

  const preview = useQuery({
    queryKey: ['invite', token, signedIn ? 'in' : 'out'],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/invites/{token}', { params: { path: { token } } }),
      ),
    enabled: me.isSuccess,
    retry: false,
  });
  const demo = useQuery({
    queryKey: ['demo-personas'],
    queryFn: async () => unwrap(await api.GET('/api/demo/personas')),
    enabled: signedOut,
    retry: false,
  });
  const join = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/invites/{token}/join', {
          params: { path: { token } },
        }),
      ),
  });

  if (join.isSuccess) {
    return <Navigate to={`/trips/${join.data.trip_id}`} replace />;
  }

  const refusal =
    join.error instanceof ApiError && join.error.status === 409
      ? REFUSALS[join.error.message]
      : undefined;
  if (refusal !== undefined) {
    return <Notice {...refusal} />;
  }
  if (join.error instanceof ApiError && join.error.status === 404) {
    return <Notice {...BAD_LINK} />;
  }

  if (me.isError || preview.isError) {
    if (preview.error instanceof ApiError && preview.error.status === 404) {
      return <Notice {...BAD_LINK} />;
    }
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
          onClick={() => {
            if (me.isError) {
              void me.refetch();
            } else {
              void preview.refetch();
            }
          }}
          className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
        >
          Retry loading
        </button>
      </div>
    );
  }

  if (me.isPending || preview.isPending) {
    return <Loading />;
  }

  const invite = preview.data;
  if (invite.already_member && invite.trip_id) {
    return <Navigate to={`/trips/${invite.trip_id}`} replace />;
  }

  if (signedOut) {
    const next = encodeURIComponent(`/join/${token}`);
    const demoAvailable = demo.isSuccess && demo.data.length > 0;
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
          {invite.organiser_name} invited you to {invite.trip_name}
        </h1>
        <p className="mt-2 text-base">Sign in to join and see who's in.</p>
        <div className="mt-6 flex flex-col gap-2">
          <Link to={`/signin?next=${next}`} className={BUTTON_CLASS}>
            Sign in to join
          </Link>
          {demoAvailable && (
            <Link to={`/demo?next=${next}`} className={QUIET_CLASS}>
              Join as a demo friend
            </Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <div className="rounded-xl border border-border p-6">
        <h1 className="text-balance break-words text-xl font-semibold leading-[1.2]">
          Join {invite.trip_name}?
        </h1>
        <p className="mt-2 text-base">
          {invite.organiser_name} is organising. In so far:{' '}
          {invite.members.join(', ')}.
        </p>
        {join.isError && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {SUBMIT_FAILED_MESSAGE}
          </p>
        )}
        <div className="mt-6 flex flex-col gap-2">
          <button
            type="button"
            disabled={join.isPending}
            aria-busy={join.isPending}
            onClick={() => join.mutate()}
            className={BUTTON_CLASS}
          >
            Join trip
          </button>
          <Link to="/" className={QUIET_CLASS}>
            Decline invite
          </Link>
        </div>
      </div>
    </div>
  );
}
