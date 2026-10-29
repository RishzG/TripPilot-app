import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { ApiError, api, unwrap } from '../../lib/api';
import { SavePayPalButton } from '../paypal/SavePayPalButton';

function displayName(slug: string, personaSlug: string | null): string {
  const base = personaSlug ?? slug;
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/**
 * Team-only page where a person logs in AS one sandbox buyer in PayPal's own popup and approves
 * saving it (UD-1, D-14). The control is the same save-PayPal button members use, pointed at the
 * pool paths for this buyer's slug. No password is asked for or stored here; the popup is PayPal's.
 * An unknown slug, or a visitor who is not an admin, sees the standard not-found text.
 */
export function EnrolPoolBuyerPage() {
  const { slug = '' } = useParams();
  const queryClient = useQueryClient();
  const buyers = useQuery({
    queryKey: ['admin', 'pool-buyers'],
    queryFn: async () => unwrap(await api.GET('/api/paypal/pool/buyers')),
    retry: false,
  });
  const [outcome, setOutcome] = useState<'idle' | 'enrolled' | 'failed'>(
    'idle',
  );

  if (
    buyers.error instanceof ApiError &&
    (buyers.error.status === 401 || buyers.error.status === 403)
  ) {
    return <p className="p-4 text-muted-foreground">Page not found</p>;
  }
  if (buyers.isPending) {
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <div
          aria-busy="true"
          aria-hidden="true"
          className="h-14 rounded-lg bg-muted motion-safe:animate-pulse"
        />
      </div>
    );
  }
  if (buyers.isError) {
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <div role="alert" className="rounded-lg border border-border p-4">
          <h2 className="text-xl font-semibold leading-[1.2]">
            We couldn't load that.
          </h2>
          <p className="mt-2 text-muted-foreground">
            Check your connection and try again.
          </p>
          <button
            type="button"
            onClick={() => void buyers.refetch()}
            className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
          >
            Retry loading
          </button>
        </div>
      </div>
    );
  }

  const buyer = buyers.data.find((row) => row.slug === slug);
  if (buyer === undefined || buyer.status === 'retired') {
    return <p className="p-4 text-muted-foreground">Page not found</p>;
  }
  const name = displayName(buyer.slug, buyer.persona_slug);
  const enrolled = outcome === 'enrolled';

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Enrol {name}
      </h1>
      <p className="mt-2 text-muted-foreground">
        Log in to PayPal as this sandbox buyer in the popup, then approve.
      </p>
      {buyer.sandbox_email !== null && (
        <p className="mt-2 break-all text-sm text-muted-foreground">
          {buyer.sandbox_email}
        </p>
      )}

      <div className="mt-6">
        {enrolled ? (
          <p role="status" className="text-base font-semibold">
            {name} is enrolled.
          </p>
        ) : (
          <>
            {outcome === 'failed' && (
              <p
                role="alert"
                className="mb-4 flex items-start gap-2 text-sm text-destructive"
              >
                <CircleAlert
                  aria-hidden="true"
                  size={16}
                  className="mt-0.5 shrink-0"
                />
                Couldn't enrol {name}. Log in as that sandbox buyer in the
                popup, approve the save, then try again.
              </p>
            )}
            <SavePayPalButton
              setupTokenPath={`/api/paypal/pool/${buyer.slug}/setup-token`}
              paymentTokenPath={`/api/paypal/pool/${buyer.slug}/payment-token`}
              onSaved={() => {
                setOutcome('enrolled');
                void queryClient.invalidateQueries({
                  queryKey: ['admin', 'pool-buyers'],
                });
              }}
              onFailed={() => setOutcome('failed')}
            />
          </>
        )}
      </div>

      <Link
        to="/admin/pool"
        className="mt-6 inline-flex min-h-11 items-center rounded-lg border border-border px-4 text-base font-semibold"
      >
        Back to the pool
      </Link>
    </div>
  );
}
