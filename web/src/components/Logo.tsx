import { Compass } from 'lucide-react';
import { Link } from 'react-router';

/**
 * The TripPilot logo (D-48 option A, "Compass tile"): a 32px coral tile with a white lucide
 * Compass, then the wordmark. Token classes only. The link carries the accessible name and the
 * wordmark is `aria-hidden`, so a screen reader hears one name and a test that looks for the text
 * `TripPilot` on a page does not find a second match. web/public/favicon.svg is the same tile.
 */
export function Logo() {
  return (
    <Link
      to="/"
      aria-label="TripPilot, my trips"
      className="inline-flex min-h-11 items-center gap-2 rounded-lg"
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Compass aria-hidden="true" size={20} strokeWidth={2} />
      </span>
      <span
        aria-hidden="true"
        className="text-xl font-semibold leading-[1.2] text-foreground"
      >
        TripPilot
      </span>
    </Link>
  );
}
