/*
 * LandingHero, adapted for TripPilot tokens from the 21st.dev component "Minimal Centered Hero"
 * (id: hero-24).
 *   Author:      LN (@ln-dev7, library lndev-ui)
 *   Source:      https://21st.dev/@ln-dev7/components/hero-24
 *   Licence:     MIT, as stated on the component page (the registry JSON carries no licence field)
 *   Retrieved:   2026-10-29 (registry JSON, SHA-256 14baf5365bb90013d740a777aa4e033e4ad743c8c0a75cf463e1c253b1c99aba)
 * Kept from the source: the centered column and its heading, paragraph and call-to-action order,
 * and the trailing arrow on the primary button. Replaced: the eyebrow pill, the oversized inline
 * type scale, the pill-shaped button, the min-height and vertical padding, and all copy (see
 * 01-UI-SPEC.md "Registry Safety", adaptation checklist). Colours, type, spacing and radii come
 * from the theme tokens in src/index.css only.
 */
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/button';

export interface LandingHeroProps {
  /** Where `Start a trip` goes; the signed-out landing sends visitors through sign-in first. */
  startHref: string;
  /** Show `Try the demo` only once demo mode is known to be on (UI-SPEC "E13 Landing hero"). */
  demoHref?: string;
}

/**
 * The signed-out landing hero (UI-SPEC "Landing hero"): one H1, one paragraph and the call to
 * action. `Start a trip` is the only coral element; `Try the demo` is outline. The whole block
 * enters once on first paint (250ms fade and 8px slide), and not at all under reduced motion.
 */
export function LandingHero({ startHref, demoHref }: LandingHeroProps) {
  return (
    <section className="mx-auto w-full max-w-2xl px-4 py-12 text-center motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-250">
      <div className="flex flex-col items-center gap-6">
        <h1 className="text-display font-semibold text-balance break-words text-foreground">
          Plan the trip. Split it fairly.
        </h1>
        <p className="text-base text-muted-foreground">
          Get your group from "we should go somewhere" to booked, without anyone
          chasing money.
        </p>
        <div className="flex w-full flex-col gap-4 md:w-auto md:flex-row md:justify-center">
          <Button asChild className="w-full md:w-auto">
            <Link to={startHref}>
              Start a trip
              <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
          {demoHref !== undefined && (
            <Button asChild variant="outline" className="w-full md:w-auto">
              <Link to={demoHref}>Try the demo</Link>
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
