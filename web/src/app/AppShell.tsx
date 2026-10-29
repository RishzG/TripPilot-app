import { UserRound } from 'lucide-react';
import { Outlet, useMatch } from 'react-router';
import { BottomTabBar } from '@/components/BottomTabBar';
import { Logo } from '@/components/Logo';
import { SandboxBanner } from '@/components/SandboxBanner';
import { Badge } from '@/components/ui/badge';
import { Toaster } from '@/components/ui/sonner';
import { useMe } from '../features/auth/useMe';
import { AccountMenu } from './AccountMenu';

/**
 * Marks every screen a demo persona sees, so nobody mistakes it for a real sign-in (D-15). Under
 * 360px the badge collapses to its icon with the text kept for screen readers, so the logo, the
 * badge and the avatar button still fit a 320px header.
 */
function DemoPersonaBadge() {
  const me = useMe();
  if (me.data?.kind !== 'persona') {
    return null;
  }
  return (
    <Badge>
      <UserRound aria-hidden="true" className="hidden max-[359px]:block" />
      <span className="max-[359px]:sr-only">Demo persona</span>
    </Badge>
  );
}

/**
 * The trip the URL points at, or null. `/trips/new` is the start-trip form, not a trip, so it
 * gets no trip tab bar.
 */
function useTripId(): string | null {
  const match = useMatch({ path: '/trips/:tripId', end: false });
  const tripId = match?.params.tripId;
  return tripId !== undefined && tripId !== 'new' ? tripId : null;
}

/**
 * Root layout (D-41, D-44): the `Skip to content` link, the sandbox banner (on every route,
 * including 404 and error screens), a sticky header with the logo and the account menu, the page
 * content, and on phones inside a trip the bottom tab bar. Pages own their own column widths and
 * the trip page's two-pane grid (UI-SPEC "Page containers"); the shell is full width.
 */
export function AppShell() {
  const tripId = useTripId();
  return (
    <div className="min-h-screen bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-4 focus-visible:z-50 focus-visible:rounded-lg focus-visible:bg-background focus-visible:px-4 focus-visible:py-2 focus-visible:text-base focus-visible:font-semibold"
      >
        Skip to content
      </a>
      <SandboxBanner />
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between gap-2 border-b border-border bg-background px-4 md:h-16 md:px-8">
        <Logo />
        <div className="flex items-center gap-2">
          <DemoPersonaBadge />
          <AccountMenu />
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className={`outline-none ${tripId ? 'pb-24 md:pb-0' : ''}`}
      >
        <Outlet />
      </main>
      {tripId && <BottomTabBar tripId={tripId} />}
      <Toaster />
    </div>
  );
}
