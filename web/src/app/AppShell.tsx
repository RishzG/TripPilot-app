import { Link, Outlet } from 'react-router';
import { Toaster } from 'sonner';
import { SandboxBanner } from '../components/SandboxBanner';
import { useMe } from '../features/auth/useMe';

/** Marks every screen a demo persona sees, so nobody mistakes it for a real sign-in (D-15). */
function DemoPersonaBadge() {
  const me = useMe();
  if (me.data?.kind !== 'persona') {
    return null;
  }
  return (
    <span className="rounded-lg border border-border bg-muted px-2 py-1 text-sm font-semibold">
      Demo persona
    </span>
  );
}

/**
 * Root layout: the sandbox banner sits above a slim header and the route outlet on every
 * route (D-41). The full header (logo tile, account menu) arrives with 01-16 and 01-25.
 */
export function AppShell() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <SandboxBanner />
      <header className="flex min-h-14 items-center justify-between gap-2 border-b border-border px-4">
        <Link to="/" className="text-base font-semibold">
          TripPilot
        </Link>
        <DemoPersonaBadge />
      </header>
      <main>
        <Outlet />
      </main>
      <Toaster
        position="top-center"
        duration={4000}
        theme="light"
        closeButton
        visibleToasts={3}
      />
    </div>
  );
}
