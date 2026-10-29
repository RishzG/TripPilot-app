import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { api, unwrap } from '../../lib/api';
import { useMe } from '../auth/useMe';
import { SavePayPalButton } from '../paypal/SavePayPalButton';
import { LookForm } from './LookForm';

const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

const OUTLINE_BUTTON =
  'inline-flex min-h-11 items-center justify-center rounded-lg border border-border px-4 text-base font-semibold disabled:opacity-50';
const DANGER_BUTTON =
  'inline-flex min-h-11 items-center justify-center rounded-lg border border-destructive px-4 text-base font-semibold text-destructive disabled:opacity-50';
const SECTION = 'rounded-xl border border-border p-4';
const HEADING = 'text-xl font-semibold leading-[1.2]';

interface ConfirmProps {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  destructive: boolean;
  pending: boolean;
  failed: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * An inline confirm for the account page's two risky actions. The least destructive button has
 * initial focus (UI-SPEC "Dialogs"); `Escape` backs out. 01-16 swaps this for the shadcn
 * alert-dialog without changing the copy or the labels.
 */
function Confirm({
  title,
  body,
  confirmLabel,
  cancelLabel,
  destructive,
  pending,
  failed,
  onConfirm,
  onCancel,
}: ConfirmProps) {
  const titleId = useId();
  const bodyId = useId();
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => cancel.current?.focus(), []);
  return (
    <div
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          onCancel();
        }
      }}
      className="mt-4 flex flex-col gap-2 rounded-lg border border-border bg-muted p-4"
    >
      <p id={titleId} className="text-base font-semibold">
        {title}
      </p>
      <p id={bodyId} className="text-sm">
        {body}
      </p>
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {SUBMIT_FAILED_MESSAGE}
        </p>
      )}
      <div className="flex flex-col gap-2 md:flex-row">
        <button
          type="button"
          disabled={pending}
          aria-busy={pending}
          onClick={onConfirm}
          className={destructive ? DANGER_BUTTON : OUTLINE_BUTTON}
        >
          {confirmLabel}
        </button>
        <button
          type="button"
          ref={cancel}
          onClick={onCancel}
          className={OUTLINE_BUTTON}
        >
          {cancelLabel}
        </button>
      </div>
    </div>
  );
}

function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div>
      <p className="font-semibold">We couldn't load that.</p>
      <p className="mt-1 text-muted-foreground">
        Check your connection and try again.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className={`mt-2 ${OUTLINE_BUTTON}`}
      >
        Retry loading
      </button>
    </div>
  );
}

/**
 * Saved PayPal for the signed-in member only (D-07, D-08): the status comes from the caller's own
 * status endpoint, nobody else's is ever requested or shown. Removing deletes our record and the
 * PayPal vault token (DELETE /api/paypal/vault) after an explicit confirm.
 */
function PayPalSection() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const status = useQuery({
    queryKey: ['vault-status'],
    queryFn: async () => unwrap(await api.GET('/api/paypal/vault/status')),
    retry: false,
  });
  const remove = useMutation({
    mutationFn: async () => unwrap(await api.DELETE('/api/paypal/vault')),
    onSuccess: (updated) => {
      queryClient.setQueryData(['vault-status'], updated);
      setConfirming(false);
    },
  });

  let content: ReactNode;
  if (status.isError) {
    content = <LoadError onRetry={() => void status.refetch()} />;
  } else if (status.isPending) {
    content = (
      <p aria-busy="true" className="text-muted-foreground">
        Checking PayPal
      </p>
    );
  } else if (status.data.saved) {
    content = (
      <>
        <p>
          <span className="rounded-lg border border-money px-2 py-1 text-sm font-semibold text-money">
            PayPal saved
          </span>
        </p>
        {confirming ? (
          <Confirm
            title="Remove saved PayPal?"
            body="We'll delete it from TripPilot and from PayPal's vault. You can save it again any time."
            confirmLabel="Remove saved PayPal"
            cancelLabel="Keep saved PayPal"
            destructive
            pending={remove.isPending}
            failed={remove.isError}
            onConfirm={() => remove.mutate()}
            onCancel={() => {
              remove.reset();
              setConfirming(false);
            }}
          />
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className={`mt-4 ${OUTLINE_BUTTON}`}
          >
            Remove saved PayPal
          </button>
        )}
      </>
    );
  } else {
    content = (
      <>
        <p>No PayPal saved yet.</p>
        <div className="mt-4">
          <SavePayPalButton
            setupTokenPath="/api/paypal/vault/setup-token"
            paymentTokenPath="/api/paypal/vault/payment-token"
            onSaved={() => {
              setSaveFailed(false);
              void queryClient.invalidateQueries({
                queryKey: ['vault-status'],
              });
            }}
            onFailed={() => setSaveFailed(true)}
          />
        </div>
        {saveFailed && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {SUBMIT_FAILED_MESSAGE}
          </p>
        )}
        <p className="mt-2 text-sm text-muted-foreground">
          You'll need it to commit to a trip.
        </p>
      </>
    );
  }

  return (
    <section aria-labelledby="account-paypal" className={SECTION}>
      <h2 id="account-paypal" className={`${HEADING} mb-4`}>
        PayPal
      </h2>
      {content}
    </section>
  );
}

/** Sign out here, or on every phone and browser (D-10). Both end on the sign-in page. */
function SessionsSection() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  function leave() {
    navigate('/signin');
    queryClient.clear();
  }
  const signOut = useMutation({
    mutationFn: async () => {
      const { response } = await api.POST('/api/auth/signout');
      if (!response.ok) {
        throw new Error(`Sign out failed (${response.status})`);
      }
    },
    onSuccess: leave,
  });
  const signOutEverywhere = useMutation({
    mutationFn: async () => {
      const { response } = await api.POST('/api/auth/signout-everywhere');
      if (!response.ok) {
        throw new Error(`Sign out failed (${response.status})`);
      }
    },
    onSuccess: leave,
  });

  return (
    <section aria-labelledby="account-sessions" className={SECTION}>
      <h2 id="account-sessions" className={`${HEADING} mb-4`}>
        Sessions
      </h2>
      {signOut.isError && (
        <p role="alert" className="mb-2 text-sm text-destructive">
          {SUBMIT_FAILED_MESSAGE}
        </p>
      )}
      <div className="flex flex-col gap-2">
        <button
          type="button"
          disabled={signOut.isPending}
          aria-busy={signOut.isPending}
          onClick={() => signOut.mutate()}
          className={OUTLINE_BUTTON}
        >
          Sign out
        </button>
        {!confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className={OUTLINE_BUTTON}
          >
            Sign out everywhere
          </button>
        )}
      </div>
      {confirming && (
        <Confirm
          title="Sign out everywhere?"
          body="You'll be signed out on every phone and browser, including this one."
          confirmLabel="Sign out everywhere"
          cancelLabel="Keep me signed in"
          destructive={false}
          pending={signOutEverywhere.isPending}
          failed={signOutEverywhere.isError}
          onConfirm={() => signOutEverywhere.mutate()}
          onCancel={() => {
            signOutEverywhere.reset();
            setConfirming(false);
          }}
        />
      )}
    </section>
  );
}

/**
 * The account page (D-06 to D-10, D-45): nickname and avatar, saved PayPal (remove it here) and
 * sign out, here or everywhere. Only the signed-in member's own data is shown.
 */
export function AccountPage() {
  const me = useMe();

  if (me.isError) {
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <LoadError onRetry={() => void me.refetch()} />
      </div>
    );
  }
  if (me.isPending) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
        <p className="text-muted-foreground">Loading your account</p>
      </div>
    );
  }

  const account = me.data;
  if (account === null) {
    return (
      <Navigate to={`/signin?next=${encodeURIComponent('/account')}`} replace />
    );
  }
  const isPersona = account.kind === 'persona' || account.is_persona;
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6 p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Account
      </h1>
      <section aria-labelledby="account-look" className={SECTION}>
        <h2 id="account-look" className={`${HEADING} mb-4`}>
          Your look
        </h2>
        {isPersona ? (
          <p className="text-muted-foreground">
            This demo persona's look is fixed.
          </p>
        ) : (
          <LookForm me={account} />
        )}
      </section>
      <PayPalSection />
      <SessionsSection />
    </div>
  );
}
