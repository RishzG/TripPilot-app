import type { RouteObject } from 'react-router';
import { EnrolPoolBuyerPage } from './EnrolPoolBuyerPage';
import { PoolBuyersPage } from './PoolBuyersPage';
import { SandboxChecksPage } from './SandboxChecksPage';

/** Routes for the admin feature, mounted by app/router.tsx under the shell. */
export const adminRoutes: RouteObject[] = [
  { path: 'admin/sandbox', element: <SandboxChecksPage /> },
  { path: 'admin/pool', element: <PoolBuyersPage /> },
  { path: 'admin/pool/enrol/:slug', element: <EnrolPoolBuyerPage /> },
];
