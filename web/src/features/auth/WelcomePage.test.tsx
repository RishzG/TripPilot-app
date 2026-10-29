import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { WelcomePage } from './WelcomePage';

interface ButtonProps {
  setupTokenPath: string;
  paymentTokenPath: string;
  onSaved: () => void;
  onFailed: (reason: 'cancelled' | 'error') => void;
}

const button = vi.hoisted(() => ({ props: null as null | ButtonProps }));

// Stand-in for the PayPal SDK control: each outcome the real popup can end in has a test button.
vi.mock('../paypal/SavePayPalButton', () => ({
  SavePayPalButton: (props: ButtonProps) => {
    button.props = props;
    return (
      <div>
        <button type="button" onClick={() => props.onSaved()}>
          sdk-saved
        </button>
        <button type="button" onClick={() => props.onFailed('error')}>
          sdk-failed
        </button>
        <button type="button" onClick={() => props.onFailed('cancelled')}>
          sdk-cancelled
        </button>
      </div>
    );
  },
}));

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const patch = api.PATCH as unknown as Mock;

interface Reply {
  status: number;
  data?: unknown;
}

function reply({ status, data }: Reply) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

function serve(routes: Record<string, Reply>) {
  get.mockImplementation(async (path: string) =>
    reply(routes[path] ?? { status: 404, data: { detail: 'Not Found' } }),
  );
}

const ME: Reply = {
  status: 200,
  data: {
    id: 'me-1',
    display_name: 'Jo',
    nickname: null,
    avatar_kind: 'initials',
    avatar_key: null,
    kind: 'member',
    is_persona: false,
  },
};
const SIGNED_OUT: Reply = { status: 401, data: { detail: 'Not signed in' } };
const TRIP: Reply = {
  status: 200,
  data: {
    id: 'trip-1',
    name: 'Tahoe weekend',
    is_organiser: false,
    joining_closed: false,
    members: [],
    removed_members: null,
  },
};
const NOT_SAVED: Reply = { status: 200, data: { saved: false } };
const SAVED: Reply = { status: 200, data: { saved: true } };

const ROUTES = {
  '/api/me': ME,
  '/api/trips/{trip_id}': TRIP,
  '/api/paypal/vault/status': NOT_SAVED,
};

const FAILED_COPY = "Couldn't save PayPal — try again or skip for now";

function renderWelcome() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/welcome/:tripId', element: <WelcomePage /> },
      { path: '/trips/:tripId', element: <p>Trip page for the group</p> },
      { path: '/signin', element: <p>Sign in page</p> },
    ],
    { initialEntries: ['/welcome/trip-1'] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe('WelcomePage', () => {
  beforeEach(() => {
    get.mockReset();
    patch.mockReset();
    button.props = null;
  });

  it('welcomes the new member and offers to save PayPal or skip', async () => {
    serve(ROUTES);
    renderWelcome();

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Welcome to Tahoe weekend',
      }),
    ).toBeTruthy();
    expect(screen.getByText('Save PayPal for this trip')).toBeTruthy();
    const skip = screen.getByRole('link', { name: 'Skip for now' });
    expect(skip.getAttribute('href')).toBe('/trips/trip-1');
    expect(button.props?.setupTokenPath).toBe('/api/paypal/vault/setup-token');
    expect(button.props?.paymentTokenPath).toBe(
      '/api/paypal/vault/payment-token',
    );
  });

  it('skipping lands on the trip', async () => {
    serve(ROUTES);
    const router = renderWelcome();

    fireEvent.click(await screen.findByRole('link', { name: 'Skip for now' }));

    expect(await screen.findByText('Trip page for the group')).toBeTruthy();
    expect(router.state.location.pathname).toBe('/trips/trip-1');
  });

  it.each([
    ['sdk-failed', 'a failed save'],
    ['sdk-cancelled', 'a closed or blocked popup'],
  ])('%s (%s) shows the retry message and keeps both actions', async (id) => {
    serve(ROUTES);
    renderWelcome();
    await screen.findByText('Save PayPal for this trip');

    fireEvent.click(screen.getByRole('button', { name: id }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(FAILED_COPY);
    expect(screen.getByRole('button', { name: 'sdk-saved' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Skip for now' })).toBeTruthy();
  });

  it('a successful save lands on the trip', async () => {
    serve(ROUTES);
    const router = renderWelcome();
    await screen.findByText('Save PayPal for this trip');

    fireEvent.click(screen.getByRole('button', { name: 'sdk-saved' }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/trips/trip-1'),
    );
  });

  it('goes straight to the trip when PayPal is already saved', async () => {
    serve({ ...ROUTES, '/api/paypal/vault/status': SAVED });
    const router = renderWelcome();

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/trips/trip-1'),
    );
    expect(screen.queryByText('Save PayPal for this trip')).toBeNull();
  });

  it('still lets the member in when the saved-PayPal status cannot be read', async () => {
    serve({
      ...ROUTES,
      '/api/paypal/vault/status': { status: 500, data: { detail: 'boom' } },
    });
    renderWelcome();

    expect(await screen.findByText('Save PayPal for this trip')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Skip for now' })).toBeTruthy();
  });

  it('sends a signed-out visitor to sign in and back here', async () => {
    serve({ ...ROUTES, '/api/me': SIGNED_OUT });
    const router = renderWelcome();

    await waitFor(() => expect(router.state.location.pathname).toBe('/signin'));
    expect(router.state.location.search).toBe(
      `?next=${encodeURIComponent('/welcome/trip-1')}`,
    );
  });

  it('opens the trip page when the trip cannot be read', async () => {
    serve({
      ...ROUTES,
      '/api/trips/{trip_id}': { status: 404, data: { detail: 'Not Found' } },
    });
    const router = renderWelcome();

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/trips/trip-1'),
    );
  });

  describe('avatar step', () => {
    it('offers the picker with the nickname prefilled from the PayPal name', async () => {
      serve(ROUTES);
      renderWelcome();

      expect(
        await screen.findByRole('heading', {
          level: 2,
          name: 'Pick your look',
        }),
      ).toBeTruthy();
      expect(
        screen.getByText(
          'Initials or an illustration. You can change it later.',
        ),
      ).toBeTruthy();
      const field = screen.getByLabelText(
        'Your name in the group',
      ) as HTMLInputElement;
      expect(field.value).toBe('Jo');
      expect(screen.getByText('Friends see this name.')).toBeTruthy();
      expect(
        within(screen.getByRole('radiogroup', { name: 'Avatar' })).getAllByRole(
          'radio',
        ),
      ).toHaveLength(17);
      expect(screen.getByRole('button', { name: 'Save my look' })).toBeTruthy();
    });

    it('does not ask again once the member has an illustrated avatar', async () => {
      serve({
        ...ROUTES,
        '/api/me': {
          status: 200,
          data: {
            ...(ME.data as object),
            avatar_kind: 'illustrated',
            avatar_key: 'sam',
          },
        },
      });
      renderWelcome();

      await screen.findByText('Save PayPal for this trip');
      expect(screen.queryByText('Pick your look')).toBeNull();
    });

    it('does not ask a demo persona', async () => {
      serve({
        ...ROUTES,
        '/api/me': {
          status: 200,
          data: { ...(ME.data as object), kind: 'persona', is_persona: true },
        },
      });
      renderWelcome();

      await screen.findByText('Save PayPal for this trip');
      expect(screen.queryByText('Pick your look')).toBeNull();
    });

    it('saves the look with PATCH /api/me without blocking the trip', async () => {
      serve(ROUTES);
      patch.mockResolvedValue(
        reply({
          status: 200,
          data: {
            ...(ME.data as object),
            nickname: 'Jojo',
            avatar_kind: 'illustrated',
            avatar_key: 'sam',
          },
        }),
      );
      const router = renderWelcome();
      await screen.findByText('Pick your look');

      fireEvent.change(screen.getByLabelText('Your name in the group'), {
        target: { value: 'Jojo' },
      });
      fireEvent.click(screen.getByRole('radio', { name: 'Avatar 2' }));
      fireEvent.click(screen.getByRole('button', { name: 'Save my look' }));

      await waitFor(() =>
        expect(patch).toHaveBeenCalledWith('/api/me', {
          body: {
            nickname: 'Jojo',
            avatar_kind: 'illustrated',
            avatar_key: 'sam',
          },
        }),
      );
      expect(router.state.location.pathname).toBe('/welcome/trip-1');
      expect(screen.getByText('Pick your look')).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Skip for now' })).toBeTruthy();
    });

    it('lets the member skip without saving a look', async () => {
      serve(ROUTES);
      const router = renderWelcome();

      fireEvent.click(
        await screen.findByRole('link', { name: 'Skip for now' }),
      );

      await waitFor(() =>
        expect(router.state.location.pathname).toBe('/trips/trip-1'),
      );
      expect(patch).not.toHaveBeenCalled();
    });
  });
});
