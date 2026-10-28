import type { RouteObject } from 'react-router';
import { createBrowserRouter } from 'react-router';
import { AppShell } from './AppShell';

export function buildRoutes(): RouteObject[] {
  return [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <h1>TripPilot</h1> },
        { path: '*', element: <p>Page not found</p> },
      ],
    },
  ];
}

export const router = createBrowserRouter(buildRoutes());
