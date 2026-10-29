import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleAlert } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { Link } from 'react-router';
import { ApiError, api, unwrap } from '../../lib/api';

const CELL = 'px-3 py-2 text-left align-top text-sm';
const HEAD = 'px-3 py-2 text-left text-sm font-semibold';
const FIELD =
  'min-h-11 w-full rounded-lg border border-muted-foreground bg-background px-4 text-base';
const DASH = '—';

const SLUG_TAKEN_MESSAGE = 'That slug is already in the pool.';
const INVALID_MESSAGE =
  'Use lowercase letters, digits and dashes for the slugs, and a full email address.';
const ADD_FAILED_MESSAGE =
  "Couldn't add that buyer. Nothing was changed, so try again.";

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  enrolled: 'Enrolled',
  retired: 'Retired',
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return SLUG_TAKEN_MESSAGE;
    }
    if (error.status === 422) {
      return INVALID_MESSAGE;
    }
  }
  return ADD_FAILED_MESSAGE;
}

/**
 * Team-only list of the simulated-friend buyers for this environment (D-12, D-14), with a small
 * form to add a buyer row. Each row links to its enrolment page, where the save-PayPal popup runs.
 * No token id is ever shown: the API returns slug, persona, sandbox email and status only.
 */
export function PoolBuyersPage() {
  const queryClient = useQueryClient();
  const buyers = useQuery({
    queryKey: ['admin', 'pool-buyers'],
    queryFn: async () => unwrap(await api.GET('/api/paypal/pool/buyers')),
    retry: false,
  });
  const [slug, setSlug] = useState('');
  const [persona, setPersona] = useState('');
  const [email, setEmail] = useState('');
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/paypal/pool/buyers', {
          body: {
            slug: slug.trim(),
            persona_slug: persona.trim() || null,
            sandbox_email: email.trim() || null,
          },
        }),
      ),
    onSuccess: async () => {
      setSlug('');
      setPersona('');
      setEmail('');
      await queryClient.invalidateQueries({
        queryKey: ['admin', 'pool-buyers'],
      });
    },
  });

  if (
    buyers.error instanceof ApiError &&
    (buyers.error.status === 401 || buyers.error.status === 403)
  ) {
    return <p className="p-4 text-muted-foreground">Page not found</p>;
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (slug.trim().length > 0) {
      add.mutate();
    }
  }

  const rows = buyers.data;
  return (
    <div className="mx-auto w-full max-w-5xl p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Pool buyers
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Sandbox buyers that stand in for friends. Each one saves PayPal once.
      </p>

      {buyers.isError && (
        <div role="alert" className="mt-6 rounded-lg border border-border p-4">
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
      )}

      <section className="mt-6" aria-labelledby="buyers-heading">
        <h2 id="buyers-heading" className="text-xl font-semibold leading-[1.2]">
          Buyers
        </h2>
        <div className="mt-2">
          {rows === undefined ? (
            buyers.isError ? null : (
              <div
                aria-busy="true"
                aria-hidden="true"
                className="h-14 rounded-lg bg-muted motion-safe:animate-pulse"
              />
            )
          ) : rows.length === 0 ? (
            <p className="text-muted-foreground">No pool buyers yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[40rem] border-collapse">
                <thead className="bg-muted">
                  <tr>
                    <th className={HEAD}>Slug</th>
                    <th className={HEAD}>Persona</th>
                    <th className={HEAD}>Sandbox email</th>
                    <th className={HEAD}>Status</th>
                    <th className={HEAD}>
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((buyer) => (
                    <tr key={buyer.slug} className="border-t border-border">
                      <td className={`${CELL} break-all`}>{buyer.slug}</td>
                      <td className={CELL}>{buyer.persona_slug ?? DASH}</td>
                      <td className={`${CELL} break-all`}>
                        {buyer.sandbox_email ?? DASH}
                      </td>
                      <td className={CELL}>
                        {STATUS_LABEL[buyer.status] ?? buyer.status}
                      </td>
                      <td className={CELL}>
                        {buyer.status === 'retired' ? null : (
                          <Link
                            to={`/admin/pool/enrol/${buyer.slug}`}
                            aria-label={`${buyer.status === 'enrolled' ? 'Enrol again' : 'Enrol'} ${buyer.slug}`}
                            className="inline-flex min-h-11 items-center rounded-lg border border-border px-4 text-base font-semibold"
                          >
                            {buyer.status === 'enrolled'
                              ? 'Enrol again'
                              : 'Enrol'}
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="mt-8" aria-labelledby="add-heading">
        <h2 id="add-heading" className="text-xl font-semibold leading-[1.2]">
          Add a buyer
        </h2>
        <form
          noValidate
          onSubmit={onSubmit}
          className="mt-2 flex max-w-md flex-col gap-4"
        >
          <div className="flex flex-col gap-2">
            <label htmlFor="pool-slug" className="text-sm font-semibold">
              Slug
            </label>
            <input
              id="pool-slug"
              type="text"
              value={slug}
              placeholder="maya"
              autoComplete="off"
              onChange={(event) => setSlug(event.target.value)}
              className={FIELD}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor="pool-persona" className="text-sm font-semibold">
              Persona slug
            </label>
            <input
              id="pool-persona"
              type="text"
              value={persona}
              placeholder="maya"
              autoComplete="off"
              onChange={(event) => setPersona(event.target.value)}
              className={FIELD}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor="pool-email" className="text-sm font-semibold">
              Sandbox email
            </label>
            <input
              id="pool-email"
              type="email"
              value={email}
              placeholder="sb-example@personal.example.com"
              autoComplete="off"
              onChange={(event) => setEmail(event.target.value)}
              className={FIELD}
            />
          </div>
          {add.isError && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <CircleAlert aria-hidden="true" size={16} />
              {errorMessage(add.error)}
            </p>
          )}
          <button
            type="submit"
            disabled={add.isPending}
            aria-busy={add.isPending}
            className="min-h-11 w-full rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground disabled:opacity-50"
          >
            Add buyer
          </button>
        </form>
      </section>
    </div>
  );
}
