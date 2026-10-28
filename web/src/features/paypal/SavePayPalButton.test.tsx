import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { SavePayPalButton } from './SavePayPalButton';

interface SdkProps {
  createVaultToken: () => Promise<{ vaultSetupToken: string }>;
  onApprove: (data: {
    fundingSource: string;
    vaultSetupToken: string;
  }) => Promise<void>;
  onCancel: () => void;
  onError: (error: Error) => void;
}

const sdk = vi.hoisted(() => ({
  provider: null as null | Record<string, unknown>,
  button: null as null | SdkProps,
}));

vi.mock('@paypal/react-paypal-js/sdk-v6', () => ({
  PayPalProvider: (
    props: { children: ReactNode } & Record<string, unknown>,
  ) => {
    const { children, ...rest } = props;
    sdk.provider = rest;
    return <div data-testid="paypal-provider">{children}</div>;
  },
  // Stand-in for the SDK control: a real click would call createVaultToken, open the PayPal
  // popup, then call onApprove, onCancel or onError. Each outcome has its own test button.
  PayPalSavePaymentButton: (props: SdkProps) => {
    sdk.button = props;
    return (
      <div>
        <button
          type="button"
          onClick={async () => {
            const { vaultSetupToken } = await props.createVaultToken();
            await props.onApprove({ fundingSource: 'paypal', vaultSetupToken });
          }}
        >
          sdk-approve
        </button>
        <button
          type="button"
          onClick={async () => {
            try {
              await props.createVaultToken();
            } catch (error) {
              props.onError(error as Error);
            }
          }}
        >
          sdk-create-only
        </button>
        <button type="button" onClick={() => props.onCancel()}>
          sdk-cancel
        </button>
        <button
          type="button"
          onClick={() => props.onError(new Error('popup failed'))}
        >
          sdk-error
        </button>
      </div>
    );
  },
}));

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const fetchMock = vi.fn();

const SETUP_PATH = '/api/paypal/vault/setup-token';
const PAYMENT_PATH = '/api/paypal/vault/payment-token';

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function serveConfig(ok = true) {
  get.mockResolvedValue(
    ok
      ? {
          data: { clientId: 'client-id-123', environment: 'sandbox' },
          response: { ok: true, status: 200 } as Response,
        }
      : {
          error: { detail: 'down' },
          response: { ok: false, status: 500 } as Response,
        },
  );
}

function renderButton() {
  const onSaved = vi.fn();
  const onFailed = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <SavePayPalButton
        setupTokenPath={SETUP_PATH}
        paymentTokenPath={PAYMENT_PATH}
        onSaved={onSaved}
        onFailed={onFailed}
      />
    </QueryClientProvider>,
  );
  return { onSaved, onFailed, view };
}

beforeEach(() => {
  sdk.provider = null;
  sdk.button = null;
  get.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  serveConfig();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SavePayPalButton', () => {
  it('wraps the SDK button in a provider built from the public client id', async () => {
    renderButton();

    await screen.findByRole('button', { name: 'sdk-approve' });

    expect(get).toHaveBeenCalledWith('/api/paypal/config');
    expect(sdk.provider).toMatchObject({
      clientId: 'client-id-123',
      environment: 'sandbox',
      components: ['paypal-payments'],
    });
  });

  it('passes createVaultToken as a function so the click reaches the SDK first', async () => {
    renderButton();

    await screen.findByRole('button', { name: 'sdk-approve' });

    expect(typeof sdk.button?.createVaultToken).toBe('function');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('posts the setup path, then the payment path with the setup token, then calls onSaved', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { vaultSetupToken: 'SETUP-1' }))
      .mockResolvedValueOnce(json(200, { saved: true }));
    const { onSaved, onFailed, view } = renderButton();

    fireEvent.click(await screen.findByRole('button', { name: 'sdk-approve' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      SETUP_PATH,
      expect.objectContaining({ method: 'POST', credentials: 'same-origin' }),
    );
    const [path, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(path).toBe(PAYMENT_PATH);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      vaultSetupToken: 'SETUP-1',
    });
    expect(onFailed).not.toHaveBeenCalled();
    expect(view.container.textContent).not.toContain('SETUP-1');
  });

  it('calls onFailed with cancelled and does nothing else when the buyer cancels', async () => {
    const { onSaved, onFailed } = renderButton();

    fireEvent.click(await screen.findByRole('button', { name: 'sdk-cancel' }));

    expect(onFailed).toHaveBeenCalledExactlyOnceWith('cancelled');
    expect(onSaved).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('calls onFailed with error when the SDK reports an error', async () => {
    const { onSaved, onFailed } = renderButton();

    fireEvent.click(await screen.findByRole('button', { name: 'sdk-error' }));

    expect(onFailed).toHaveBeenCalledExactlyOnceWith('error');
    expect(onSaved).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('calls onFailed with error when the server refuses the payment token', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { vaultSetupToken: 'SETUP-2' }))
      .mockResolvedValueOnce(json(502, { detail: 'paypal_unavailable' }));
    const { onSaved, onFailed } = renderButton();

    fireEvent.click(await screen.findByRole('button', { name: 'sdk-approve' }));

    await waitFor(() =>
      expect(onFailed).toHaveBeenCalledExactlyOnceWith('error'),
    );
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('makes createVaultToken reject, so the SDK reports an error, when the setup call fails', async () => {
    fetchMock.mockResolvedValueOnce(
      json(502, { detail: 'paypal_unavailable' }),
    );
    const { onSaved, onFailed } = renderButton();

    fireEvent.click(
      await screen.findByRole('button', { name: 'sdk-create-only' }),
    );

    await waitFor(() =>
      expect(onFailed).toHaveBeenCalledExactlyOnceWith('error'),
    );
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('calls onFailed with error and shows no SDK control when the config cannot be loaded', async () => {
    serveConfig(false);
    const { onFailed } = renderButton();

    await waitFor(() =>
      expect(onFailed).toHaveBeenCalledExactlyOnceWith('error'),
    );
    expect(screen.queryByRole('button', { name: 'sdk-approve' })).toBeNull();
  });
});
