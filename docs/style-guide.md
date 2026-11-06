# TripPilot style guide

This is the shared reference for extending and changing the current web UI. It describes the
implemented styles as of November 6, 2026. Update it alongside changes to the shared theme or
components. Older mockups in `docs/planning/` are design history; use the current source files
linked below for exact values and behavior.

## Sources to edit

| Change | Source |
|---|---|
| Colors, font family, radii, motion, Tailwind token mappings | [web/src/index.css](../web/src/index.css) |
| Font loading | [web/src/main.tsx](../web/src/main.tsx) |
| Buttons, cards, inputs, badges, dialogs and other primitives | [web/src/components/ui](../web/src/components/ui/) |
| Class merging (`cn`) | [web/src/lib/utils.ts](../web/src/lib/utils.ts) |
| Global shell, skip link and mobile trip navigation | [AppShell.tsx](../web/src/app/AppShell.tsx), [BottomTabBar.tsx](../web/src/components/BottomTabBar.tsx) |
| Trip sidebar, header and content layout | [TripWorkspace.tsx](../web/src/features/trips/TripWorkspace.tsx) |
| Brand mark and favicon | [Logo.tsx](../web/src/components/Logo.tsx), [favicon.svg](../web/public/favicon.svg) |
| Avatars and asset license | [Avatar.tsx](../web/src/components/Avatar.tsx), [avatar assets](../web/src/assets/avatars/) |
| Palette accessibility checks | [theme.contrast.test.ts](../web/src/theme.contrast.test.ts) |

## Visual language and colors

Use warm paper surfaces, charcoal text, coral actions, thin borders, generous spacing and simple
Lucide line icons. The implemented theme is light only. Components consume semantic Tailwind
classes such as `bg-background`, `text-foreground` and `border-border`; change the central CSS
variables to change the palette.

| Role / CSS token | Current value | Usage |
|---|---|---|
| `background` / `foreground` | `#fffaf5` / `#1c1917` | Page surface and main text |
| `card`, `popover` | `#ffffff` | Cards and floating surfaces; foreground is charcoal |
| `primary` / `primary-foreground` | `#bf4f3f` / `#ffffff` | Main coral action |
| `primary-hover` | `#a83e30` | Primary action hover |
| `secondary`, `muted` | `#f5ede4` | Subtle surfaces |
| `muted-foreground` | `#57534e` | Supporting text |
| `accent` | `#efe3d6` | Menu and ghost-button hover surface |
| `border` / `input` | `#e7d9ca` / `#78716c` | Dividers / visible form-control borders |
| `ring` | `#bf4f3f` | Keyboard focus |
| `destructive` / `destructive-foreground` | `#b91c1c` / `#ffffff` | Destructive actions and errors |
| `money` / `money-foreground` | `#1d4ed8` / `#ffffff` | Payment-related emphasis |
| `money-surface` | `#eff6ff` | Payment-related surface |
| `sandbox-banner` / `sandbox-banner-foreground` | `#fef3c7` / `#78350f` | Sandbox notice |

`accent` is a neutral hover surface, not the brand color. Reserve blue money styling for payment
moments, such as saved PayPal status and amounts. Avatar colors use the eight `avatar-*` tokens
with `avatar-foreground`; reuse the Avatar component rather than choosing new colors per page.
Avoid raw color literals in components. The standalone SVG favicon mirrors the theme colors
manually, so update it when changing the brand palette.

## Typography, spacing and components

- Font: self-hosted Plus Jakarta Sans Variable, with system sans-serif fallbacks.
- Core type scale: `text-sm` (14px), `text-base` (16px), `text-xl` (20px) and
  `text-display` (28px). Display and shared card titles use a 1.2 line height; base text uses 1.5.
  Some workspace metadata currently uses smaller text; follow nearby components when extending it.
- Use semibold for shared button labels and headings, with muted text for supporting descriptions.
- Shared cards use a 12px radius (`rounded-xl`), a thin border and 16px padding, increasing to
  24px at `md`. Buttons and inputs use an 8px radius (`rounded-lg`).
- Use Tailwind spacing utilities and the existing layouts. Shared buttons are 44px high; icon
  buttons are 44px square. Keep controls usable at narrow widths.
- Reuse `Button` variants: `default`, `outline`, `secondary`, `ghost`, `destructive`, `link`.
  Reserve the coral default for the main action of the screen.
- Compose existing Card, Input, Label, Badge and dialog primitives before creating new ones.
  Use `cn` for conditional classes and overrides. Shared primitives use Radix and
  class-variance-authority where applicable.
- Reuse Logo (coral compass tile and wordmark), Lucide icons and the existing avatar assets.
  Hide decorative icons from assistive technology and name icon-only controls.

## Layout and states

The trip workspace uses a 208px sidebar from `md` upward, a trip/member header and a scrolling
content area. Below `md`, navigation wraps and the shell also supplies mobile trip tabs. Preserve
the shared sandbox banner, skip link and navigation when adding screens.

Chat is the default trip view. Plan has its own itinerary/map view; Preferences and Group are
separate views. Follow the current workspace rather than the older side-by-side concept.
Use the shared EmptyState, ErrorRetry, SkeletonList and UI spinner/skeleton components for states.
Keep unavailable features and demo content clearly labeled; do not imply successful booking or
payment from a visual state alone.

## Making a style change

1. Edit theme tokens for a global change, shared primitives for a component-wide change, or the
   feature component for a local layout change. Keep semantic color classes in feature code.
2. Preserve visible keyboard focus (the global outline is 2px with a 2px offset), labels,
   keyboard access and reduced-motion support. Standard button transitions are 150ms;
   `prefers-reduced-motion` makes animations and transitions effectively instant.
3. For palette changes, run `npm test -- --run src/theme.contrast.test.ts` from `web/`.
   The existing checks require 4.5:1 for listed text pairs and 3:1 for listed graphics/control
   pairs. Adjust tokens when a pair fails. Primary-colored text on the muted surface is a known
   unsupported pairing; use foreground text there.
4. For component changes, run `npm run typecheck`, `npm run lint` and relevant existing tests
   from `web/`. Inspect affected screens at phone and desktop widths, including loading, empty,
   error, disabled and keyboard-focus states.
5. Update this guide when conventions change, and record behavior changes and verification in
   [docs/progress](progress/README.md) so teammates can follow the handoff.
