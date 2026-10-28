import { Outlet } from 'react-router';
import { SandboxBanner } from '../components/SandboxBanner';

/** Root layout: the sandbox banner sits above the route outlet on every route (D-41). */
export function AppShell() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <SandboxBanner />
      <main>
        <Outlet />
      </main>
    </div>
  );
}
