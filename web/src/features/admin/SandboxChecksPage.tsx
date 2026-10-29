import { useQuery } from '@tanstack/react-query';
import { LoaderCircle } from 'lucide-react';
import { ApiError, api, unwrap } from '../../lib/api';

const CELL = 'px-3 py-2 text-left align-top text-sm';
const HEAD = 'px-3 py-2 text-left text-sm font-semibold';
const MONEY_CELL = `${CELL} break-all tabular-nums text-money`;
const DASH = '—';

function dash(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === ''
    ? DASH
    : String(value);
}

function time(value: string | null | undefined): string {
  if (!value) {
    return DASH;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return `${parsed.toISOString().slice(0, 19).replace('T', ' ')} UTC`;
}

function dollars(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) {
    return DASH;
  }
  return `$${(cents / 100).toFixed(2)}`;
}

function SkeletonRows() {
  return (
    <div aria-busy="true" className="flex flex-col gap-2">
      {[0, 1, 2].map((row) => (
        <div
          key={row}
          aria-hidden="true"
          className="h-14 rounded-lg bg-muted motion-safe:animate-pulse"
        />
      ))}
    </div>
  );
}

function ErrorRetry({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-border p-4">
      <h2 className="text-xl font-semibold leading-[1.2]">
        We couldn't load that.
      </h2>
      <p className="mt-2 text-muted-foreground">
        Check your connection and try again.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
      >
        Retry loading
      </button>
    </div>
  );
}

/**
 * Team-only, read-only view of the latest holds and webhooks (D-37). It offers exactly one
 * control, Refresh checks: nothing here can move money. Visitors who are not on the admin list
 * see the standard not-found text.
 */
export function SandboxChecksPage() {
  const checks = useQuery({
    queryKey: ['admin', 'sandbox-checks'],
    queryFn: async () => unwrap(await api.GET('/api/admin/sandbox-checks')),
    retry: false,
  });

  if (
    checks.error instanceof ApiError &&
    (checks.error.status === 401 || checks.error.status === 403)
  ) {
    return <p className="p-4 text-muted-foreground">Page not found</p>;
  }

  const refreshing = checks.isFetching;
  const data = checks.data;
  const placeholder = checks.isError ? null : <SkeletonRows />;
  return (
    <div className="mx-auto w-full max-w-5xl p-4 pt-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
          Sandbox checks
        </h1>
        <button
          type="button"
          onClick={() => void checks.refetch()}
          disabled={refreshing}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-border px-4 text-base font-semibold disabled:opacity-50"
        >
          {refreshing && (
            <LoaderCircle
              aria-hidden="true"
              className="size-4 motion-safe:animate-spin"
            />
          )}
          Refresh checks
        </button>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        Read-only. This page cannot move money.
      </p>

      {checks.isError && (
        <div className="mt-6">
          <ErrorRetry onRetry={() => void checks.refetch()} />
        </div>
      )}

      <section className="mt-6" aria-labelledby="holds-heading">
        <h2 id="holds-heading" className="text-xl font-semibold leading-[1.2]">
          Holds
        </h2>
        <div className="mt-2">
          {data === undefined ? (
            placeholder
          ) : data.holds.length === 0 ? (
            <p className="text-muted-foreground">No holds yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[40rem] border-collapse">
                <thead className="bg-muted">
                  <tr>
                    <th className={HEAD}>Time</th>
                    <th className={HEAD}>Action</th>
                    <th className={HEAD}>Authorization</th>
                    <th className={HEAD}>Status</th>
                    <th className={HEAD}>Amount</th>
                    <th className={HEAD}>Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {data.holds.map((hold) => (
                    <tr key={hold.ledger_id} className="border-t border-border">
                      <td className={`${CELL} tabular-nums`}>
                        {time(hold.occurred_at)}
                      </td>
                      <td className={CELL}>{hold.action}</td>
                      <td className={MONEY_CELL}>
                        {dash(hold.authorization_id)}
                      </td>
                      <td className={CELL}>{dash(hold.status)}</td>
                      <td className={MONEY_CELL}>
                        {dollars(hold.amount_cents)}
                      </td>
                      <td className={`${CELL} tabular-nums`}>
                        {time(hold.expires_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="mt-6" aria-labelledby="webhooks-heading">
        <h2
          id="webhooks-heading"
          className="text-xl font-semibold leading-[1.2]"
        >
          Webhooks
        </h2>
        <div className="mt-2">
          {data === undefined ? (
            placeholder
          ) : data.webhooks.length === 0 ? (
            <p className="text-muted-foreground">No webhooks received yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[40rem] border-collapse">
                <thead className="bg-muted">
                  <tr>
                    <th className={HEAD}>Received</th>
                    <th className={HEAD}>Event</th>
                    <th className={HEAD}>Resource</th>
                    <th className={HEAD}>Verification</th>
                    <th className={HEAD}>Processed</th>
                  </tr>
                </thead>
                <tbody>
                  {data.webhooks.map((hook) => (
                    <tr key={hook.event_id} className="border-t border-border">
                      <td className={`${CELL} tabular-nums`}>
                        {time(hook.received_at)}
                      </td>
                      <td className={`${CELL} break-all`}>{hook.event_type}</td>
                      <td className={MONEY_CELL}>{dash(hook.resource_id)}</td>
                      <td className={CELL}>{hook.verification_status}</td>
                      <td className={`${CELL} tabular-nums`}>
                        {time(hook.processed_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
