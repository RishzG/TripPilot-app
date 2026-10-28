import type { RouteObject } from 'react-router';
import { createBrowserRouter } from 'react-router';
import { accountRoutes } from '../features/account/routes';
import { adminRoutes } from '../features/admin/routes';
import { authRoutes } from '../features/auth/routes';
import { PersonaPickerPage } from '../features/demo/PersonaPickerPage';
import { tripRoutes } from '../features/trips/routes';
import { AppShell } from './AppShell';

/**
 * Route table with AppShell as the root layout; tests reuse it with createMemoryRouter.
 * Feature route arrays are composed here, so later plans add pages in their own feature folder.
 */
export function buildRoutes(): RouteObject[] {
  return [
    {
      path: '/',
      element: <AppShell />,
      children: [
        ...tripRoutes,
        ...authRoutes,
        ...adminRoutes,
        ...accountRoutes,
        { path: 'demo', element: <PersonaPickerPage /> },
        {
          path: '*',
          element: <p className="p-4 text-muted-foreground">Page not found</p>,
        },
      ],
    },
  ];
}

export const router = createBrowserRouter(buildRoutes());
