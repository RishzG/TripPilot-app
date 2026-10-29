import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { SignInPage } from './SignInPage';

const logins = vi.hoisted(() => [] as { email: string; password: string }[]);
vi.mock('./judgeLogins', () => ({ JUDGE_LOGINS: logins }));

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;

function reply(status: number, data: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

function servePersonas(status: number, data: unknown) {
  get.mockImplementation(async (path: string) =>
    path === '/api/demo/personas'
      ? reply(status, data)
      : reply(404, { detail: 'Not Found' }),
  );
}

function renderSignIn(search = '') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [{ path: '/signin', element: <SignInPage /> }],
    { initialEntries: [`/signin${search}`] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('SignInPage', () => {
  beforeEach(() => {
    get.mockReset();
    logins.splice(0, logins.length);
    servePersonas(404, { detail: 'Not Found' });
  });

  it('offers Log in with PayPal and says what it will use', async () => {
    renderSignIn();

    expect(
      screen.getByRole('heading', { level: 1, name: 'Sign in to TripPilot' }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "We'll use your PayPal name and email to set you up. Nothing is charged.",
      ),
    ).toBeTruthy();
    const login = screen.getByRole('link', { name: 'Log in with PayPal' });
    expect(login.getAttribute('href')).toBe('/api/auth/paypal/start');
  });

  it('carries a same-app next path through to the start route', () => {
    renderSignIn(`?next=${encodeURIComponent('/trips/new')}`);

    const login = screen.getByRole('link', { name: 'Log in with PayPal' });
    expect(login.getAttribute('href')).toBe(
      `/api/auth/paypal/start?next=${encodeURIComponent('/trips/new')}`,
    );
  });

  it('drops a next that is not a path inside the app', () => {
    renderSignIn(`?next=${encodeURIComponent('//evil.example')}`);

    const login = screen.getByRole('link', { name: 'Log in with PayPal' });
    expect(login.getAttribute('href')).toBe('/api/auth/paypal/start');
  });

  it('shows Try the demo only when the demo personas exist', async () => {
    servePersonas(200, [{ slug: 'maya', name: 'Maya' }]);
    renderSignIn(`?next=${encodeURIComponent('/trips/new')}`);

    const demo = await screen.findByRole('link', { name: 'Try the demo' });
    expect(demo.getAttribute('href')).toBe(
      `/demo?next=${encodeURIComponent('/trips/new')}`,
    );
  });

  it('hides Try the demo when demo mode is off', async () => {
    renderSignIn();
    await waitFor(() => expect(get).toHaveBeenCalled());

    expect(screen.queryByRole('link', { name: 'Try the demo' })).toBeNull();
  });

  it('does not render the judge logins block while the list is empty', () => {
    renderSignIn();

    expect(screen.queryByText('Judge sandbox logins')).toBeNull();
  });

  it('lists judge logins with copy buttons when there are some', async () => {
    logins.push({ email: 'judge@example.test', password: 'pw-judge-1' });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    renderSignIn();

    expect(screen.getByText('Judge sandbox logins')).toBeTruthy();
    expect(
      screen.getByText(
        'Sandbox PayPal accounts for trying the real log-in. No real money is involved.',
      ),
    ).toBeTruthy();
    expect(screen.getByText('judge@example.test')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Copy email' }));
    fireEvent.click(screen.getByRole('button', { name: 'Copy password' }));
    expect(writeText).toHaveBeenCalledWith('judge@example.test');
    expect(writeText).toHaveBeenCalledWith('pw-judge-1');
  });

  it.each([
    ['cancelled', "You cancelled at PayPal. Log in again when you're ready."],
    ['failed', "Couldn't log you in with PayPal. Try again."],
  ])('explains a ?error=%s return from PayPal', (error, message) => {
    renderSignIn(`?error=${error}`);

    expect(screen.getByRole('alert').textContent).toBe(message);
    expect(
      screen.getByRole('link', { name: 'Log in with PayPal' }),
    ).toBeTruthy();
  });

  it('shows no alert on a normal visit', () => {
    renderSignIn();

    expect(screen.queryByRole('alert')).toBeNull();
  });
});
