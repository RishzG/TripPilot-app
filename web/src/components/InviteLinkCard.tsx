/*
 * InviteLinkCard, adapted for TripPilot tokens from the 21st.dev component "Share Link With
 * Scope" (id: share-access-1).
 *   Author:      @felipemenezes098 (ui.flexnative.com)
 *   Source:      https://21st.dev/@felipemenezes098/components/share-access-1
 *   Licence:     MIT, as stated on the component page (the registry JSON carries no licence field)
 *   Retrieved:   2026-10-29 (registry JSON, SHA-256 933872d270a5992cc8b8ffbdbc54a56b86765341d427e949bb7b8027d7339bca)
 * Kept from the source: the card structure, the read-only link field with a link icon, the copy
 * action with a copied state, and the open/closed link-visibility concept (here the existing
 * `Close joining` / `Open joining` button and caption instead of a switch). Deleted: the
 * "use client" directive, the permission and expiry selects, the InputGroup wrapper, the icon-only
 * copy button, the demo URL constant (the link is a prop) and all source copy. The source's
 * copy() never touched the clipboard; this one calls navigator.clipboard.writeText. Colours,
 * type, spacing and radii come from the theme tokens in src/index.css only.
 */
import { AlertCircle, Check, Copy, Link2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Spinner } from '@/components/ui/spinner';

/** How long the Copy icon stays a Check after a successful copy (UI-SPEC motion rule 2). */
export const COPIED_ICON_MS = 2000;
/** How long `Reset? ...` waits before putting the Reset link button back (same as other confirms). */
export const RESET_CONFIRM_MS = 6000;

export interface InviteLinkCardProps {
  /** The full invite URL; `undefined` while it is loading. */
  url: string | undefined;
  /** The trip is not accepting new members (D-23). */
  joiningClosed: boolean;
  /** The invite lookup failed: show a retry instead of the field. */
  loadFailed?: boolean;
  onRetry?: () => void;
  /** Rotate the link; only called after the inline `Yes, reset` confirmation. */
  onResetLink: () => void;
  resetPending?: boolean;
  /** Close or open joining; one tap, no confirmation. */
  onToggleJoining: () => void;
  togglePending?: boolean;
  /** A reset or close/open request failed: show the submit-error copy. */
  actionFailed?: boolean;
  /**
   * Play the 250ms entrance. The trip page passes false for a card that is part of the first
   * paint, so a cached re-render never animates (UI-SPEC "Interaction and Motion").
   */
  animateEntrance?: boolean;
}

/**
 * The organiser's invite card (UI-SPEC "Invite card"): H2, a read-only link field, the single
 * full-width `Copy invite link` action, then `Reset link` and `Close joining` / `Open joining`.
 * Motion is tw-animate-css utilities with `motion-safe:` only; the Copy icon still swaps to Check
 * under reduced motion.
 */
export function InviteLinkCard({
  url,
  joiningClosed,
  loadFailed = false,
  onRetry,
  onResetLink,
  resetPending = false,
  onToggleJoining,
  togglePending = false,
  actionFailed = false,
  animateEntrance = true,
}: InviteLinkCardProps) {
  const field = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  // The field cross-fades when the link is replaced by a reset, never for the first value.
  const [shownUrl, setShownUrl] = useState({ url, swapped: false });
  if (url !== shownUrl.url) {
    setShownUrl({
      url,
      swapped: shownUrl.url !== undefined && url !== undefined,
    });
  }

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = setTimeout(() => setCopied(false), COPIED_ICON_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    if (!confirmingReset) {
      return;
    }
    const timer = setTimeout(() => setConfirmingReset(false), RESET_CONFIRM_MS);
    return () => clearTimeout(timer);
  }, [confirmingReset]);

  async function copy() {
    if (url === undefined) {
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopyFailed(false);
      setCopied(true);
      toast('Copy the invite and drop it in your group chat');
    } catch {
      setCopyFailed(true);
      field.current?.select();
    }
  }

  const CopyIcon = copied ? Check : Copy;
  return (
    <Card
      className={
        animateEntrance
          ? 'motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-250'
          : undefined
      }
    >
      <CardHeader>
        <h2 className="text-xl font-semibold leading-[1.2]">Invite link</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {loadFailed ? (
          <div className="flex flex-col gap-2">
            <p className="text-muted-foreground">We couldn't load that.</p>
            <Button
              type="button"
              variant="outline"
              onClick={onRetry}
              className="self-start"
            >
              Retry loading
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Link2
                aria-hidden="true"
                className="size-5 shrink-0 text-muted-foreground"
              />
              <Input
                key={shownUrl.url}
                ref={field}
                type="text"
                readOnly
                aria-label="Invite link address"
                value={url ?? ''}
                className={
                  shownUrl.swapped
                    ? 'truncate motion-safe:animate-in motion-safe:fade-in motion-safe:duration-150'
                    : 'truncate'
                }
              />
            </div>
            {copyFailed && (
              <p className="text-sm text-muted-foreground">
                Press and hold to copy the link.
              </p>
            )}
            <Button
              type="button"
              disabled={url === undefined}
              onClick={copy}
              className="w-full"
            >
              <CopyIcon
                aria-hidden="true"
                className={
                  copied
                    ? 'motion-safe:animate-in motion-safe:zoom-in-50 motion-safe:duration-150'
                    : undefined
                }
              />
              Copy invite link
            </Button>
          </>
        )}

        <Separator />

        {confirmingReset ? (
          <div className="flex flex-col gap-2">
            <p>Reset? The old link stops working right away.</p>
            <div className="flex flex-col gap-2 min-[360px]:flex-row">
              <Button
                type="button"
                variant="destructive"
                disabled={resetPending}
                aria-busy={resetPending}
                onClick={() => {
                  onResetLink();
                  setConfirmingReset(false);
                }}
              >
                {resetPending && <Spinner />}
                Yes, reset
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setConfirmingReset(false)}
              >
                Keep old link
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2 min-[360px]:flex-row">
            <Button
              type="button"
              variant="outline"
              disabled={resetPending}
              aria-busy={resetPending}
              onClick={() => setConfirmingReset(true)}
            >
              {resetPending && <Spinner />}
              Reset link
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={togglePending}
              aria-busy={togglePending}
              onClick={onToggleJoining}
            >
              {togglePending && <Spinner />}
              {joiningClosed ? 'Open joining' : 'Close joining'}
            </Button>
          </div>
        )}

        {joiningClosed && (
          <p className="text-sm text-muted-foreground motion-safe:animate-in motion-safe:fade-in motion-safe:duration-150">
            Joining is closed. Nobody new can use the link.
          </p>
        )}
        {actionFailed && (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle aria-hidden="true" className="size-5 shrink-0" />
            Couldn't save that. Nothing was changed, so try again.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
