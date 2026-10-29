import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { api, unwrap } from '../../lib/api';
import { SavePayPalButton } from '../paypal/SavePayPalButton';
import { useMe } from './useMe';

const SAVE_FAILED_MESSAGE = "Couldn't save PayPal — try again or skip for now";

function Loading() {
  return (
    <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
      <p className="text-muted-foreground">Getting your trip ready</p>
    </div>
  );
}

/**
 * The step after joining through an invite (D-01, D-02, D-11): the member is already in. They can
 * save PayPal now with one approval, or skip; a failed, closed or blocked popup never keeps them
 * out of the trip. Saving is optional here and never charges or holds anything.
 */
export function WelcomePage() {
  const { tripId = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useMe();
  const signedIn = me.isSuccess && me.data !== null;
  const [saveFailed, setSaveFailed] = useState(false);

  const trip = useQuery({
    queryKey: ['trip', tripId],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}', {
          params: { path: { trip_id: tripId } },
        }),
      ),
    enabled: signedIn,
    retry: false,
  });
  const vault = useQuery({
    queryKey: ['vault-status'],
    queryFn: async () => unwrap(await api.GET('/api/paypal/vault/status')),
    enabled: signedIn,
    retry: false,
  });

  const tripPath = `/trips/${tripId}`;

  if (me.isSuccess && me.data === null) {
    const back = encodeURIComponent(`/welcome/${tripId}`);
    return <Navigate to={`/signin?next=${back}`} replace />;
  }
  if (me.isError) {
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
          onClick={() => void me.refetch()}
          className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
        >
          Retry loading
        </button>
      </div>
    );
  }
  if (trip.isError || vault.data?.saved === true) {
    return <Navigate to={tripPath} replace />;
  }
  if (me.isPending || trip.isPending || vault.isPending) {
    return <Loading />;
  }

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Welcome to {trip.data.name}
      </h1>
      <p className="mt-2 text-base">
        You're in. Save PayPal now so committing later takes one tap. Saving
        doesn't charge you or hold any money.
      </p>
      <section className="mt-6 rounded-xl border border-l-4 border-border border-l-money p-4">
        <p className="text-base font-semibold">Save PayPal for this trip</p>
        <div className="mt-4">
          <SavePayPalButton
            setupTokenPath="/api/paypal/vault/setup-token"
            paymentTokenPath="/api/paypal/vault/payment-token"
            onSaved={() => {
              void queryClient.invalidateQueries({
                queryKey: ['vault-status'],
              });
              navigate(tripPath, { replace: true });
            }}
            onFailed={() => setSaveFailed(true)}
          />
        </div>
        {saveFailed && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {SAVE_FAILED_MESSAGE}
          </p>
        )}
      </section>
      <Link
        to={tripPath}
        className="mt-4 inline-flex min-h-11 items-center text-base font-semibold underline"
      >
        Skip for now
      </Link>
    </div>
  );
}
