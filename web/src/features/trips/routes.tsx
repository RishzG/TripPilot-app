import type { RouteObject } from 'react-router';
import { HomePage } from './HomePage';
import { JoinPage } from './JoinPage';
import { StartTripPage } from './StartTripPage';
import { TripPage } from './TripPage';

/** Routes for starting and opening a trip, mounted by app/router.tsx under the shell. */
export const tripRoutes: RouteObject[] = [
  { index: true, element: <HomePage /> },
  { path: 'trips/new', element: <StartTripPage /> },
  { path: 'trips/:tripId', element: <TripPage /> },
  { path: 'join/:token', element: <JoinPage /> },
];
