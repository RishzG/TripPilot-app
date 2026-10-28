/** Slim top bar shown on every screen so nobody mistakes sandbox money for real money (D-41). */
export function SandboxBanner() {
  return (
    <div
      role="status"
      className="bg-sandbox-banner px-4 py-1 text-center text-sm font-medium text-sandbox-banner-foreground"
    >
      Sandbox — no real money
    </div>
  );
}
