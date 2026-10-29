import type { RouteObject } from 'react-router';
import { AccountPage } from './AccountPage';

/** Routes for the account feature (01-15); app/router.tsx spreads this array. */
export const accountRoutes: RouteObject[] = [
  { path: 'account', element: <AccountPage /> },
];
