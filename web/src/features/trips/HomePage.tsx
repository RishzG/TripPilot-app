import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { api, unwrap } from '../../lib/api';
import { useMe } from '../auth/useMe';

const PRIMARY_LINK =
  'inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground';
const OUTLINE_LINK =
  'inline-flex min-h-11 w-full items-center justify-center rounded-lg border border-border px-4 text-base font-semibold';

function LoadError({ onRetry }: { onRetry: () => void }) {
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
        onClick={onRetry}
        className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
      >
        Retry loading
      </button>
    </div>
  );
}

/** Signed-out landing: sign in first to start a trip; the demo is offered when it exists. */
function Landing() {
  const demo = useQuery({
    queryKey: ['demo-personas'],
    queryFn: async () => unwrap(await api.GET('/api/demo/personas')),
    retry: false,
  });
  const demoAvailable = demo.isSuccess && demo.data.length > 0;
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-12 text-center">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Plan the trip. Split it fairly.
      </h1>
      <p className="mt-6 text-base text-muted-foreground">
        Get your group from "we should go somewhere" to booked, without anyone
        chasing money.
      </p>
      <div className="mt-6 flex flex-col gap-4 md:flex-row md:justify-center">
        <Link
          to={`/signin?next=${encodeURIComponent('/trips/new')}`}
          className={`${PRIMARY_LINK} md:w-auto`}
        >
          Start a trip
        </Link>
        {demoAvailable && (
          <Link to="/demo" className={`${OUTLINE_LINK} md:w-auto`}>
            Try the demo
          </Link>
        )}
      </div>
    </div>
  );
}

function peopleLabel(count: number): string {
  return count === 1 ? '1 person' : `${count} people`;
}

/** My trips (D-26): every trip the signed-in account is active in. */
function MyTrips() {
  const trips = useQuery({
    queryKey: ['trips'],
    queryFn: async () => unwrap(await api.GET('/api/trips')),
    retry: false,
  });

  if (trips.isPending) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
        <p className="text-muted-foreground">Loading your trips</p>
      </div>
    );
  }
  if (trips.isError) {
    return <LoadError onRetry={() => void trips.refetch()} />;
  }

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        My trips
      </h1>
      {trips.data.length === 0 ? (
        <div className="mt-6">
          <h2 className="text-xl font-semibold leading-[1.2]">
            No trips yet — start one!
          </h2>
          <p className="mt-2 text-muted-foreground">
            Trips you start or join show up here.
          </p>
          <Link to="/trips/new" className={`mt-4 ${PRIMARY_LINK}`}>
            Start a trip
          </Link>
        </div>
      ) : (
        <>
          <Link to="/trips/new" className={`mt-6 ${PRIMARY_LINK}`}>
            Start a trip
          </Link>
          <ul className="mt-6 flex flex-col gap-4">
            {trips.data.map((trip) => (
              <li key={trip.id}>
                <Link
                  to={`/trips/${trip.id}`}
                  className="flex min-h-14 flex-col gap-1 rounded-xl border border-border p-4"
                >
                  <span className="break-words text-base font-semibold">
                    {trip.name}
                  </span>
                  <span className="flex items-center gap-2 text-sm text-muted-foreground">
                    {peopleLabel(trip.member_count)}
                    {trip.role === 'organiser' && (
                      <span className="rounded-lg border border-border bg-muted px-2 font-semibold text-foreground">
                        Organiser
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** The home page: the landing when signed out, My trips when signed in. */
export function HomePage() {
  const me = useMe();
  if (me.isPending) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
        <p className="text-muted-foreground">Loading</p>
      </div>
    );
  }
  if (me.isError) {
    return <LoadError onRetry={() => void me.refetch()} />;
  }
  return me.data === null ? <Landing /> : <MyTrips />;
}
