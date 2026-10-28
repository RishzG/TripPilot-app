import { Outlet } from 'react-router';

// Stub for the RED phase: no banner yet.
export function AppShell() {
  return (
    <main>
      <Outlet />
    </main>
  );
}
