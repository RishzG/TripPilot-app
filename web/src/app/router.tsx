import type { RouteObject } from 'react-router';
import { createBrowserRouter } from 'react-router';
import { AppShell } from './AppShell';

/** Route table with AppShell as the root layout; tests reuse it with createMemoryRouter. */
export function buildRoutes(): RouteObject[] {
  return [
    {
      path: '/',
      element: <AppShell />,
      children: [
        {
          index: true,
          element: <h1 className="p-4 text-2xl font-semibold">TripPilot</h1>,
        },
        {
          path: '*',
          element: <p className="p-4 text-muted-foreground">Page not found</p>,
        },
      ],
    },
  ];
}

export const router = createBrowserRouter(buildRoutes());
