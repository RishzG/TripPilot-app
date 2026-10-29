import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { EnrolPoolBuyerPage } from './EnrolPoolBuyerPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const button = vi.hoisted(() => ({
  props: null as null | {
    setupTokenPath: string;
    paymentTokenPath: string;
    onSaved: () => void;
    onFailed: (reason: 'cancelled' | 'error') => void;
  },
}));

vi.mock('../paypal/SavePayPalButton', () => ({
  SavePayPalButton: (props: NonNullable<typeof button.props>) => {
    button.props = props;
    return <button type="button">sdk-save-paypal</button>;
  },
}));

const get = api.GET as unknown as Mock;

function answer(status: number, data?: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

const BUYERS = [
  {
    slug: 'maya',
    persona_slug: 'maya',
    sandbox_email: 'sb-maya@personal.example.com',
    status: 'pending',
  },
  {
    slug: 'sam',
    persona_slug: null,
    sandbox_email: null,
    status: 'enrolled',
  },
  {
    slug: 'old',
    persona_slug: null,
    sandbox_email: null,
    status: 'retired',
  },
];

function renderPage(slug: string) {
  const router = createMemoryRouter(
    [{ path: '/admin/pool/enrol/:slug', element: <EnrolPoolBuyerPage /> }],
    { initialEntries: [`/admin/pool/enrol/${slug}`] },
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('EnrolPoolBuyerPage', () => {
  beforeEach(() => {
    get.mockReset();
    button.props = null;
  });

  it('shows the locked heading and body and points the save control at this buyer', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage('maya');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Enrol Maya' }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'Log in to PayPal as this sandbox buyer in the popup, then approve.',
      ),
    ).toBeTruthy();
    expect(screen.getByText('sb-maya@personal.example.com')).toBeTruthy();
    expect(screen.getByText('sdk-save-paypal')).toBeTruthy();
    expect(button.props?.setupTokenPath).toBe(
      '/api/paypal/pool/maya/setup-token',
    );
    expect(button.props?.paymentTokenPath).toBe(
      '/api/paypal/pool/maya/payment-token',
    );
    expect(get).toHaveBeenCalledWith('/api/paypal/pool/buyers');
  });

  it('falls back to the slug for the name when there is no persona', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage('sam');

    expect(
      await screen.findByRole('heading', { name: 'Enrol Sam' }),
    ).toBeTruthy();
  });

  it('replaces the control with the success line once saved', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage('maya');
    await screen.findByText('sdk-save-paypal');

    act(() => button.props?.onSaved());

    expect(await screen.findByText('Maya is enrolled.')).toBeTruthy();
    expect(screen.queryByText('sdk-save-paypal')).toBeNull();
  });

  it('shows the failure alert and keeps the control for a retry', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage('maya');
    await screen.findByText('sdk-save-paypal');

    act(() => button.props?.onFailed('cancelled'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(
      "Couldn't enrol Maya. Log in as that sandbox buyer in the popup, approve the save, then try again.",
    );
    expect(screen.getByText('sdk-save-paypal')).toBeTruthy();
  });

  it('shows the standard not-found text for an unknown or retired slug', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage('nobody');
    expect(await screen.findByText('Page not found')).toBeTruthy();
  });

  it('shows the standard not-found text for a retired buyer', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage('old');
    expect(await screen.findByText('Page not found')).toBeTruthy();
    expect(screen.queryByText('sdk-save-paypal')).toBeNull();
  });

  it('shows the standard not-found text to someone who is not an admin', async () => {
    get.mockResolvedValue(answer(403, { detail: 'Forbidden' }));
    renderPage('maya');
    expect(await screen.findByText('Page not found')).toBeTruthy();
  });
});
