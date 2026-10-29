import type { RouteObject } from 'react-router';
import { JoinFailedPage } from './JoinFailedPage';
import { SignInPage } from './SignInPage';
import { WelcomePage } from './WelcomePage';

/** Routes for the auth feature, mounted by app/router.tsx under the shell. */
export const authRoutes: RouteObject[] = [
  { path: 'signin', element: <SignInPage /> },
  { path: 'welcome/:tripId', element: <WelcomePage /> },
  { path: 'join-failed', element: <JoinFailedPage /> },
];
