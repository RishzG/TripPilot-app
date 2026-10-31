import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, Navigate, useParams } from 'react-router';
import { ErrorRetry } from '@/components/ErrorRetry';
import { SkeletonList } from '@/components/SkeletonList';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Spinner } from '@/components/ui/spinner';
import { ApiError, api, unwrap } from '../../lib/api';
import { useMe } from '../auth/useMe';
import { BAD_LINK, Notice, REFUSALS } from './joinNotices';

const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

const PAGE = 'mx-auto w-full max-w-md p-4 pt-6';

/** The card skeleton while the invite resolves (UI-SPEC "E4 Join confirm card", loading). */
function Loading() {
  return (
    <div className={PAGE}>
      <SkeletonList withTitle rows={2} />
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
      <div className={PAGE}>
        <ErrorRetry
          onRetry={() => {
            if (me.isError) {
              void me.refetch();
            } else {
              void preview.refetch();
            }
          }}
        />
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
    const loginHref = `/api/auth/paypal/start?invite=${encodeURIComponent(token)}`;
    return (
      <div className={PAGE}>
        <h1 className="text-balance break-words text-display font-semibold leading-[1.2]">
          {invite.organiser_name} invited you to {invite.trip_name}
        </h1>
        <p className="mt-2 text-base">Sign in to join and see who's in.</p>
        <div className="mt-6 flex flex-col gap-2">
          <Button asChild className="w-full">
            <a href={loginHref}>Sign in to join</a>
          </Button>
          {demoAvailable && (
            <Button asChild variant="ghost" className="w-full">
              <Link to={`/demo?next=${next}`}>Join as a demo friend</Link>
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={PAGE}>
      <Card>
        <CardHeader>
          <h1 className="text-balance break-words text-xl font-semibold leading-[1.2]">
            Join {invite.trip_name}?
          </h1>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-base">
            {invite.organiser_name} is organising. In so far:{' '}
            {invite.members.join(', ')}.
          </p>
          {join.isError && (
            <p role="alert" className="text-sm text-destructive">
              {SUBMIT_FAILED_MESSAGE}
            </p>
          )}
          <div className="flex flex-col gap-2">
            <Button
              type="button"
              disabled={join.isPending}
              aria-busy={join.isPending}
              onClick={() => join.mutate()}
              className="w-full"
            >
              {join.isPending && <Spinner />}
              Join trip
            </Button>
            <Button asChild variant="ghost" className="w-full">
              <Link to="/">Decline invite</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
