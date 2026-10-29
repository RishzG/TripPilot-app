import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { SandboxChecksPage } from './SandboxChecksPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn() } };
});

const get = api.GET as unknown as Mock;

interface Reply {
  status: number;
  data?: unknown;
}

function answer({ status, data }: Reply) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

const LONG_AUTH = 'AUTH-0123456789ABCDEF0123456789ABCDEF0123456789';
const POPULATED: Reply = {
  status: 200,
  data: {
    holds: [
      {
        ledger_id: 7,
        occurred_at: '2026-10-29T12:00:00Z',
        action: 'hold.placed',
        actor_kind: 'script',
        request_id: 'req-1',
        authorization_id: LONG_AUTH,
        status: 'CREATED',
        amount_cents: 100,
        expires_at: '2026-11-27T12:00:00Z',
      },
      {
        ledger_id: 6,
        occurred_at: '2026-10-29T11:00:00Z',
        action: 'vault.token_used',
        actor_kind: 'script',
        request_id: null,
        authorization_id: null,
        status: null,
        amount_cents: null,
        expires_at: null,
      },
    ],
    webhooks: [
      {
        event_id: 'WH-1',
        event_type: 'PAYMENT.AUTHORIZATION.CREATED',
        resource_id: LONG_AUTH,
        verification_status: 'SUCCESS',
        received_at: '2026-10-29T12:00:05Z',
        processed_at: null,
      },
    ],
  },
};
const EMPTY: Reply = { status: 200, data: { holds: [], webhooks: [] } };

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SandboxChecksPage />
    </QueryClientProvider>,
  );
}

describe('SandboxChecksPage', () => {
  beforeEach(() => get.mockReset());

  it('shows the heading, caption and both sections with their rows', async () => {
    get.mockResolvedValue(answer(POPULATED));
    renderPage();

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Sandbox checks' }),
    ).toBeTruthy();
    expect(
      screen.getByText('Read-only. This page cannot move money.'),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Holds' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Webhooks' })).toBeTruthy();
    expect(await screen.findByText('hold.placed')).toBeTruthy();
    expect(screen.getByText('$1.00')).toBeTruthy();
    expect(screen.getByText('CREATED')).toBeTruthy();
    expect(screen.getByText('2026-11-27 12:00:00 UTC')).toBeTruthy();
    expect(screen.getByText('PAYMENT.AUTHORIZATION.CREATED')).toBeTruthy();
    expect(screen.getByText('SUCCESS')).toBeTruthy();
    expect(get).toHaveBeenCalledWith('/api/admin/sandbox-checks');
  });

  it('renders an em dash for a missing cell and keeps the row', async () => {
    get.mockResolvedValue(answer(POPULATED));
    renderPage();

    const row = (await screen.findByText('vault.token_used')).closest('tr');
    expect(row).not.toBeNull();
    expect(row?.textContent?.match(/—/g)?.length).toBe(4);
  });

  it('wraps long ids and uses tabular numerals and the money colour', async () => {
    get.mockResolvedValue(answer(POPULATED));
    renderPage();

    const [cell] = await screen.findAllByText(LONG_AUTH);
    expect(cell?.className).toContain('break-all');
    expect(cell?.className).toContain('tabular-nums');
    expect(cell?.className).toContain('text-money');
    expect(cell?.closest('.overflow-x-auto')).not.toBeNull();
  });

  it('shows the empty copy for both sections', async () => {
    get.mockResolvedValue(answer(EMPTY));
    renderPage();

    expect(await screen.findByText('No holds yet.')).toBeTruthy();
    expect(screen.getByText('No webhooks received yet.')).toBeTruthy();
  });

  it('shows busy skeletons while loading', async () => {
    let release: (value: ReturnType<typeof answer>) => void = () => undefined;
    get.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    renderPage();

    expect(
      await screen.findByRole('heading', { name: 'Sandbox checks' }),
    ).toBeTruthy();
    expect(document.querySelectorAll('[aria-busy="true"]').length).toBe(2);

    release(answer(EMPTY));
    expect(await screen.findByText('No holds yet.')).toBeTruthy();
    expect(document.querySelectorAll('[aria-busy="true"]').length).toBe(0);
  });

  it('offers a retry when the load fails and recovers on retry', async () => {
    get.mockResolvedValueOnce(
      answer({ status: 500, data: { detail: 'boom' } }),
    );
    renderPage();

    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(
      screen.getByText('Check your connection and try again.'),
    ).toBeTruthy();

    get.mockResolvedValue(answer(EMPTY));
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }));
    expect(await screen.findByText('No holds yet.')).toBeTruthy();
  });

  it('refreshes on demand and offers no other control', async () => {
    get.mockResolvedValue(answer(POPULATED));
    renderPage();
    await screen.findByText('hold.placed');

    expect(
      screen.getAllByRole('button').map((button) => button.textContent),
    ).toEqual(['Refresh checks']);

    fireEvent.click(screen.getByRole('button', { name: 'Refresh checks' }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it('shows the standard not-found text to someone who is not an admin', async () => {
    get.mockResolvedValue(
      answer({ status: 403, data: { detail: 'Forbidden' } }),
    );
    renderPage();

    expect(await screen.findByText('Page not found')).toBeTruthy();
    expect(screen.queryByText('Sandbox checks')).toBeNull();
  });

  it('shows the standard not-found text when signed out', async () => {
    get.mockResolvedValue(
      answer({ status: 401, data: { detail: 'Not signed in' } }),
    );
    renderPage();

    expect(await screen.findByText('Page not found')).toBeTruthy();
  });
});
