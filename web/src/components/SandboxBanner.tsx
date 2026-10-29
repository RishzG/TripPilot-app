/** Slim top bar shown on every screen so nobody mistakes sandbox money for real money (D-41). */
export function SandboxBanner() {
  return (
    <div
      role="status"
      className="flex h-7 items-center justify-center bg-sandbox-banner px-4 text-center text-sm font-semibold leading-[1.4] text-sandbox-banner-foreground"
    >
      Sandbox — no real money
    </div>
  );
}
