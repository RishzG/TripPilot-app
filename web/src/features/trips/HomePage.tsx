import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { EmptyState } from '@/components/EmptyState';
import { ErrorRetry } from '@/components/ErrorRetry';
import { LandingHero } from '@/components/LandingHero';
import { SkeletonList } from '@/components/SkeletonList';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { api, unwrap } from '../../lib/api';
import { useMe } from '../auth/useMe';

const NARROW_PAGE = 'mx-auto w-full max-w-md p-4 pt-6';

function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className={NARROW_PAGE}>
      <ErrorRetry onRetry={onRetry} />
    </div>
  );
}

function StartTripLink() {
  return (
    <Button asChild className="w-full">
      <Link to="/trips/new">Start a trip</Link>
    </Button>
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
    <LandingHero
      startHref={`/signin?next=${encodeURIComponent('/trips/new')}`}
      demoHref={demoAvailable ? '/demo' : undefined}
    />
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
      <div className={NARROW_PAGE}>
        <SkeletonList withTitle />
      </div>
    );
  }
  if (trips.isError) {
    return <LoadError onRetry={() => void trips.refetch()} />;
  }

  const title = (
    <h1 className="text-balance break-words text-display font-semibold leading-[1.2]">
      My trips
    </h1>
  );

  if (trips.data.length === 0) {
    return (
      <div className={NARROW_PAGE}>
        {title}
        <EmptyState
          className="mt-6"
          title="No trips yet — start one!"
          description="Trips you start or join show up here."
          action={<StartTripLink />}
        />
      </div>
    );
  }

  // One Start a trip link serves both layouts: full width above the list on a phone, and the
  // right-hand pane beside the list from md up (UI-SPEC "Page containers").
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6 md:max-w-5xl md:p-8">
      {title}
      <div className="mt-6 grid gap-6 md:grid-cols-[360px_1fr] md:items-start md:gap-8">
        <div className="md:col-start-2 md:row-start-1 md:rounded-xl md:border md:border-border md:bg-card md:p-6">
          <StartTripLink />
        </div>
        <ul className="flex flex-col gap-4 md:col-start-1 md:row-start-1">
          {trips.data.map((trip) => (
            <li key={trip.id}>
              <Link
                to={`/trips/${trip.id}`}
                className="block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <Card className="min-h-14 gap-1 transition-colors duration-150 ease-out hover:bg-accent">
                  <CardContent className="flex flex-col gap-1">
                    <span
                      title={trip.name}
                      className="line-clamp-2 break-words text-base font-semibold"
                    >
                      {trip.name}
                    </span>
                    <span className="flex items-center gap-2 text-sm text-muted-foreground">
                      {peopleLabel(trip.member_count)}
                      {trip.role === 'organiser' && <Badge>Organiser</Badge>}
                    </span>
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** The home page: the landing when signed out, My trips when signed in. */
export function HomePage() {
  const me = useMe();
  if (me.isPending) {
    return (
      <div className={NARROW_PAGE}>
        <SkeletonList withTitle />
      </div>
    );
  }
  if (me.isError) {
    return <LoadError onRetry={() => void me.refetch()} />;
  }
  return me.data === null ? <Landing /> : <MyTrips />;
}
