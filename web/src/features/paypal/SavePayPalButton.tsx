import {
  PayPalProvider,
  PayPalSavePaymentButton,
} from '@paypal/react-paypal-js/sdk-v6';
import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef } from 'react';
import { api, unwrap } from '../../lib/api';

export interface SavePayPalButtonProps {
  /** POST here (no body) to get `{ vaultSetupToken }` for the signed-in caller. */
  setupTokenPath: string;
  /** POST `{ vaultSetupToken }` here once the buyer approved; a 2xx means PayPal is saved. */
  paymentTokenPath: string;
  onSaved: () => void;
  onFailed: (reason: 'cancelled' | 'error') => void;
}

const SDK_COMPONENTS: ['paypal-payments'] = ['paypal-payments'];

async function post(path: string, body?: unknown): Promise<Response> {
  return fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    ...(body === undefined
      ? {}
      : {
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }),
  });
}

/**
 * The PayPal v6 "save PayPal" control (ACC-03): PayPal's own button and popup, wired to the
 * server's vault endpoints. It only ever holds the one-time setup token in memory; no token id
 * or customer id is rendered, stored or logged here, and the server never returns them.
 *
 * The control is PayPal's, so its interior is not restyled; this component sizes only the
 * container (full width on a phone, at most `max-w-sm`, minimum height 44px, UI-SPEC).
 * `createVaultToken` is passed as a function and does no awaited work before the SDK calls it,
 * so the click's user gesture reaches the popup (RESEARCH Pitfall 3).
 */
export function SavePayPalButton({
  setupTokenPath,
  paymentTokenPath,
  onSaved,
  onFailed,
}: SavePayPalButtonProps) {
  const config = useQuery({
    queryKey: ['paypal', 'config'],
    queryFn: async () => unwrap(await api.GET('/api/paypal/config')),
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });

  const handlers = useRef({ onSaved, onFailed });
  handlers.current = { onSaved, onFailed };

  const configFailed = config.isError;
  useEffect(() => {
    if (configFailed) {
      handlers.current.onFailed('error');
    }
  }, [configFailed]);

  const createVaultToken = useCallback(async () => {
    const response = await post(setupTokenPath);
    if (!response.ok) {
      throw new Error(`Could not start saving PayPal (${response.status})`);
    }
    const body = (await response.json()) as { vaultSetupToken: string };
    return { vaultSetupToken: body.vaultSetupToken };
  }, [setupTokenPath]);

  const onApprove = useCallback(
    async ({ vaultSetupToken }: { vaultSetupToken: string }) => {
      try {
        const response = await post(paymentTokenPath, { vaultSetupToken });
        if (!response.ok) {
          handlers.current.onFailed('error');
          return;
        }
      } catch {
        handlers.current.onFailed('error');
        return;
      }
      handlers.current.onSaved();
    },
    [paymentTokenPath],
  );

  const onCancel = useCallback(
    () => handlers.current.onFailed('cancelled'),
    [],
  );
  const onError = useCallback(() => handlers.current.onFailed('error'), []);

  return (
    <div className="min-h-11 w-full max-w-sm">
      {config.data ? (
        <PayPalProvider
          clientId={config.data.clientId}
          environment="sandbox"
          components={SDK_COMPONENTS}
        >
          <PayPalSavePaymentButton
            createVaultToken={createVaultToken}
            onApprove={onApprove}
            onCancel={onCancel}
            onError={onError}
          />
        </PayPalProvider>
      ) : null}
    </div>
  );
}
