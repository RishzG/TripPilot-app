import { Luggage } from 'lucide-react';
import { NavLink } from 'react-router';

/**
 * Phone bottom tab bar (D-44), shown only under 768px and only inside a trip. One tab today,
 * `Trip`; later phases add tabs, which share the width because every tab is `flex-1`. The whole
 * tab is the link (44px minimum, D-46), the active tab is coral through `aria-current="page"`,
 * and the bar pads for the iPhone home indicator with `env(safe-area-inset-bottom)`.
 */
export function BottomTabBar({ tripId }: { tripId: string }) {
  return (
    <nav
      aria-label="Trip"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="m-0 flex h-14 list-none p-0">
        <li className="flex flex-1">
          <NavLink
            to={`/trips/${tripId}`}
            end
            className="flex min-h-11 min-w-11 flex-1 flex-col items-center justify-center gap-1 text-sm font-semibold leading-[1.4] text-muted-foreground aria-[current=page]:text-primary"
          >
            <Luggage aria-hidden="true" size={24} strokeWidth={2} />
            Trip
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}
