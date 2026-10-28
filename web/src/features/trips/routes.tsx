import type { RouteObject } from 'react-router';
import { Link } from 'react-router';
import { StartTripPage } from './StartTripPage';
import { TripPage } from './TripPage';

/** Placeholder home; plan 01-05 replaces it with My trips. */
function HomePlaceholder() {
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        TripPilot
      </h1>
      <Link
        to="/trips/new"
        className="mt-6 inline-flex min-h-11 items-center rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
      >
        Start a trip
      </Link>
    </div>
  );
}

/** Routes for starting and opening a trip, mounted by app/router.tsx under the shell. */
export const tripRoutes: RouteObject[] = [
  { index: true, element: <HomePlaceholder /> },
  { path: 'trips/new', element: <StartTripPage /> },
  { path: 'trips/:tripId', element: <TripPage /> },
];
