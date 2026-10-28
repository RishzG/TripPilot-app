import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ApiError, api, unwrap } from '../../lib/api';
import { forgetSignedInState, safeNextPath } from '../auth/useMe';

/**
 * The standard not-found page. When DEMO_MODE is off the persona route does not exist, so the
 * picker shows this instead of a dead end (D-15, UI-SPEC "Demo persona picker").
 */
function NotFound() {
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-xl font-semibold leading-[1.2]">
        We can't find that page.
      </h1>
      <p className="mt-2 text-muted-foreground">The link may be old.</p>
      <Link
        to="/"
        className="mt-4 inline-flex min-h-11 items-center rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
      >
        Go to My trips
      </Link>
    </div>
  );
}

/**
 * Pick a simulated friend to be (D-13, D-18); switching is signing in as another. A `next`
 * path inside the app (an invite link) is where the visitor goes afterwards.
 */
export function PersonaPickerPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const personas = useQuery({
    queryKey: ['demo-personas'],
    queryFn: async () => unwrap(await api.GET('/api/demo/personas')),
    retry: false,
  });
  const signIn = useMutation({
    mutationFn: async (slug: string) =>
      unwrap(
        await api.POST('/api/demo/personas/{slug}/session', {
          params: { path: { slug } },
        }),
      ),
    onSuccess: () => {
      forgetSignedInState(queryClient);
      navigate(safeNextPath(searchParams.get('next'), '/trips/new'));
    },
  });

  if (personas.isPending) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
        <p className="text-muted-foreground">Loading the cast</p>
      </div>
    );
  }

  if (personas.isError) {
    if (personas.error instanceof ApiError && personas.error.status === 404) {
      return <NotFound />;
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
          onClick={() => personas.refetch()}
          className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
        >
          Retry loading
        </button>
      </div>
    );
  }

  if (personas.data.length === 0) {
    return <NotFound />;
  }

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Try the demo
      </h1>
      <p className="mt-2 text-base">
        Pick a friend to be. You can switch any time.
      </p>
      {signIn.isError && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          Couldn't save that. Nothing was changed, so try again.
        </p>
      )}
      <ul className="mt-6 flex flex-col gap-4">
        {personas.data.map((persona) => (
          <li
            key={persona.slug}
            className="flex flex-col gap-2 rounded-xl border border-border p-4"
          >
            <span className="text-base font-semibold">{persona.name}</span>
            <span className="text-sm text-muted-foreground">
              {persona.note}
            </span>
            <button
              type="button"
              disabled={signIn.isPending}
              aria-busy={signIn.isPending && signIn.variables === persona.slug}
              onClick={() => signIn.mutate(persona.slug)}
              className="min-h-11 w-full rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground disabled:opacity-50"
            >
              Continue as {persona.name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
