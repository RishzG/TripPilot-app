import type { RouteObject } from 'react-router';
import { SandboxChecksPage } from './SandboxChecksPage';

/** Routes for the admin feature, mounted by app/router.tsx under the shell. */
export const adminRoutes: RouteObject[] = [
  { path: 'admin/sandbox', element: <SandboxChecksPage /> },
];
