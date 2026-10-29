import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { toast } from 'sonner';
import type { Mock } from 'vitest';
import { AVATAR_KEYS } from '../../assets/avatars';
import { api } from '../../lib/api';
import { AccountPage } from './AccountPage';

interface ButtonProps {
  onSaved: () => void;
  onFailed: (reason: 'cancelled' | 'error') => void;
}

// Stand-in for the PayPal SDK control, as in the welcome page test.
vi.mock('../paypal/SavePayPalButton', () => ({
  SavePayPalButton: (props: ButtonProps) => (
    <div>
      <button type="button" onClick={() => props.onSaved()}>
        sdk-saved
      </button>
      <button type="button" onClick={() => props.onFailed('error')}>
        sdk-failed
      </button>
    </div>
  ),
}));
vi.mock('sonner', () => ({ toast: vi.fn() }));
vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return {
    ...actual,
    api: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() },
  };
});

const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;
const patch = api.PATCH as unknown as Mock;
const del = api.DELETE as unknown as Mock;

interface Reply {
  status: number;
  data?: unknown;
}

function answer({ status, data }: Reply) {
  return {
    data: status < 400 && status !== 204 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

const ME = {
  id: 'me-1',
  display_name: 'Josephine Park',
  nickname: null,
  avatar_kind: 'initials',
  avatar_key: null,
  kind: 'member',
  is_persona: false,
};
const PERSONA = {
  ...ME,
  display_name: 'Maya',
  avatar_kind: 'illustrated',
  avatar_key: 'maya',
  kind: 'persona',
  is_persona: true,
};

function serve(routes: Record<string, Reply>) {
  get.mockImplementation(async (path: string) =>
    answer(routes[path] ?? { status: 404, data: { detail: 'Not Found' } }),
  );
}

const SIGNED_IN: Record<string, Reply> = {
  '/api/me': { status: 200, data: ME },
  '/api/paypal/vault/status': { status: 200, data: { saved: true } },
};

function renderAccount() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/account', element: <AccountPage /> },
      { path: '/signin', element: <p>Sign in page</p> },
    ],
    { initialEntries: ['/account'] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

async function ready() {
  await screen.findByRole('heading', { level: 1, name: 'Account' });
}

describe('AccountPage look', () => {
  beforeEach(() => {
    for (const mock of [get, post, patch, del]) {
      mock.mockReset();
    }
    vi.mocked(toast).mockReset();
  });

  it('shows the three sections and prefills the nickname from the PayPal name', async () => {
    serve(SIGNED_IN);
    renderAccount();
    await ready();

    for (const name of ['Your look', 'PayPal', 'Sessions']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeTruthy();
    }
    const field = screen.getByLabelText('Nickname') as HTMLInputElement;
    expect(field.value).toBe('Josephine Park');
    expect(screen.getByRole('button', { name: 'Save my look' })).toBeTruthy();
  });

  it('offers initials plus all sixteen illustrations and selects the saved look', async () => {
    serve({
      ...SIGNED_IN,
      '/api/me': {
        status: 200,
        data: { ...ME, avatar_kind: 'illustrated', avatar_key: 'omar' },
      },
    });
    renderAccount();
    await ready();

    const group = screen.getByRole('radiogroup', { name: 'Avatar' });
    const tiles = within(group).getAllByRole('radio') as HTMLInputElement[];
    expect(tiles).toHaveLength(17);
    expect(tiles[0]?.getAttribute('aria-label')).toBe('Initials');
    expect(tiles[16]?.getAttribute('aria-label')).toBe('Avatar 16');
    expect(AVATAR_KEYS).toHaveLength(16);
    const omar = screen.getByRole('radio', {
      name: `Avatar ${AVATAR_KEYS.indexOf('omar') + 1}`,
    }) as HTMLInputElement;
    expect(omar.checked).toBe(true);
    expect(group.querySelectorAll('img')).toHaveLength(16);
  });

  it('falls back to the Initials tile when the saved key is not in the set', async () => {
    serve({
      ...SIGNED_IN,
      '/api/me': {
        status: 200,
        data: { ...ME, avatar_kind: 'illustrated', avatar_key: 'unknown' },
      },
    });
    renderAccount();
    await ready();

    const initials = screen.getByRole('radio', {
      name: 'Initials',
    }) as HTMLInputElement;
    expect(initials.checked).toBe(true);
  });

  it('saves the nickname and the chosen illustration with PATCH /api/me', async () => {
    serve(SIGNED_IN);
    patch.mockResolvedValue(
      answer({
        status: 200,
        data: {
          ...ME,
          nickname: 'Jo',
          avatar_kind: 'illustrated',
          avatar_key: 'kai',
        },
      }),
    );
    renderAccount();
    await ready();

    fireEvent.change(screen.getByLabelText('Nickname'), {
      target: { value: '  Jo  ' },
    });
    fireEvent.click(
      screen.getByRole('radio', {
        name: `Avatar ${AVATAR_KEYS.indexOf('kai') + 1}`,
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save my look' }));

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/api/me', {
        body: {
          nickname: 'Jo',
          avatar_kind: 'illustrated',
          avatar_key: 'kai',
        },
      }),
    );
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Saved'));
  });

  it('sends no key when initials are chosen', async () => {
    serve({
      ...SIGNED_IN,
      '/api/me': {
        status: 200,
        data: { ...ME, avatar_kind: 'illustrated', avatar_key: 'kai' },
      },
    });
    patch.mockResolvedValue(answer({ status: 200, data: ME }));
    renderAccount();
    await ready();

    fireEvent.click(screen.getByRole('radio', { name: 'Initials' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save my look' }));

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/api/me', {
        body: {
          nickname: 'Josephine Park',
          avatar_kind: 'initials',
          avatar_key: null,
        },
      }),
    );
  });

  it.each([
    ['', 'Add a name your friends will recognise.'],
    ['   ', 'Add a name your friends will recognise.'],
    ['x'.repeat(41), 'Keep it under 40 characters.'],
  ])(
    'blocks the nickname %j with an inline message',
    async (value, message) => {
      serve(SIGNED_IN);
      renderAccount();
      await ready();

      fireEvent.change(screen.getByLabelText('Nickname'), {
        target: { value },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Save my look' }));

      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toBe(message);
      expect(patch).not.toHaveBeenCalled();
    },
  );

  it('shows the submit-failed copy and keeps the button usable when saving fails', async () => {
    serve(SIGNED_IN);
    patch.mockResolvedValue(answer({ status: 500, data: { detail: 'boom' } }));
    renderAccount();
    await ready();

    fireEvent.click(screen.getByRole('button', { name: 'Save my look' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      "Couldn't save that. Nothing was changed, so try again.",
    );
    expect(
      (
        screen.getByRole('button', {
          name: 'Save my look',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it('keeps a demo persona look fixed and offers no form', async () => {
    serve({ ...SIGNED_IN, '/api/me': { status: 200, data: PERSONA } });
    renderAccount();
    await ready();

    expect(screen.getByText("This demo persona's look is fixed.")).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Save my look' })).toBeNull();
  });

  it('sends a signed-out visitor to sign in', async () => {
    serve({ '/api/me': { status: 401, data: { detail: 'Not signed in' } } });
    const router = renderAccount();

    await waitFor(() => expect(router.state.location.pathname).toBe('/signin'));
    expect(router.state.location.search).toBe(
      `?next=${encodeURIComponent('/account')}`,
    );
  });

  it('offers a retry when the account cannot be loaded', async () => {
    serve({ '/api/me': { status: 500, data: { detail: 'boom' } } });
    renderAccount();

    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry loading' })).toBeTruthy();
  });
});

describe('AccountPage saved PayPal', () => {
  beforeEach(() => {
    for (const mock of [get, post, patch, del]) {
      mock.mockReset();
    }
  });

  it('shows the badge and Remove saved PayPal only when PayPal is saved', async () => {
    serve(SIGNED_IN);
    renderAccount();
    await ready();

    expect(await screen.findByText('PayPal saved')).toBeTruthy();
    expect(
      screen.getByRole('button', { name: 'Remove saved PayPal' }),
    ).toBeTruthy();
    expect(screen.queryByText('No PayPal saved yet.')).toBeNull();
  });

  it('asks only for the signed-in member status and nobody else', async () => {
    serve(SIGNED_IN);
    renderAccount();
    await ready();
    await screen.findByText('PayPal saved');

    const statusCalls = get.mock.calls.filter(
      ([path]) => path === '/api/paypal/vault/status',
    );
    expect(statusCalls).toHaveLength(1);
    expect(statusCalls[0]).toHaveLength(1);
  });

  it('removes it only after the confirm, then shows the not-saved state', async () => {
    serve(SIGNED_IN);
    del.mockResolvedValue(answer({ status: 200, data: { saved: false } }));
    renderAccount();
    await ready();

    fireEvent.click(
      await screen.findByRole('button', { name: 'Remove saved PayPal' }),
    );

    const dialog = screen.getByRole('alertdialog', {
      name: 'Remove saved PayPal?',
    });
    expect(del).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain(
      "We'll delete it from TripPilot and from PayPal's vault. You can save it again any time.",
    );
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Remove saved PayPal' }),
    );

    expect(await screen.findByText('No PayPal saved yet.')).toBeTruthy();
    expect(del).toHaveBeenCalledWith('/api/paypal/vault');
    expect(
      screen.queryByRole('button', { name: 'Remove saved PayPal' }),
    ).toBeNull();
  });

  it('keeps the saved PayPal when the member backs out', async () => {
    serve(SIGNED_IN);
    renderAccount();
    await ready();

    fireEvent.click(
      await screen.findByRole('button', { name: 'Remove saved PayPal' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Keep saved PayPal' }));

    expect(del).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.getByText('PayPal saved')).toBeTruthy();
  });

  it('keeps it and says so when PayPal could not be reached', async () => {
    serve(SIGNED_IN);
    del.mockResolvedValue(answer({ status: 502, data: { detail: 'paypal' } }));
    renderAccount();
    await ready();

    fireEvent.click(
      await screen.findByRole('button', { name: 'Remove saved PayPal' }),
    );
    const dialog = screen.getByRole('alertdialog');
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Remove saved PayPal' }),
    );

    expect(await within(dialog).findByRole('alert')).toBeTruthy();
    expect(screen.getByText('PayPal saved')).toBeTruthy();
  });

  it('shows the save control and no Remove button when nothing is saved', async () => {
    serve({
      ...SIGNED_IN,
      '/api/paypal/vault/status': { status: 200, data: { saved: false } },
    });
    renderAccount();
    await ready();

    expect(await screen.findByText('No PayPal saved yet.')).toBeTruthy();
    expect(
      screen.getByText("You'll need it to commit to a trip."),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'sdk-saved' })).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: 'Remove saved PayPal' }),
    ).toBeNull();
    expect(screen.queryByText('PayPal saved')).toBeNull();
  });

  it('keeps the look and sessions usable when the PayPal status cannot be read', async () => {
    serve({
      ...SIGNED_IN,
      '/api/paypal/vault/status': { status: 500, data: { detail: 'boom' } },
    });
    renderAccount();
    await ready();

    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save my look' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy();
  });
});

describe('AccountPage sessions', () => {
  beforeEach(() => {
    for (const mock of [get, post, patch, del]) {
      mock.mockReset();
    }
  });

  it('Sign out ends this session and goes to sign in', async () => {
    serve(SIGNED_IN);
    post.mockResolvedValue(answer({ status: 204 }));
    const router = renderAccount();
    await ready();

    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => expect(router.state.location.pathname).toBe('/signin'));
    expect(post).toHaveBeenCalledWith('/api/auth/signout');
  });

  it('Sign out everywhere asks first, then calls the endpoint and goes to sign in', async () => {
    serve(SIGNED_IN);
    post.mockResolvedValue(answer({ status: 204 }));
    const router = renderAccount();
    await ready();

    fireEvent.click(
      screen.getByRole('button', { name: 'Sign out everywhere' }),
    );

    const dialog = screen.getByRole('alertdialog', {
      name: 'Sign out everywhere?',
    });
    expect(post).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain(
      "You'll be signed out on every phone and browser, including this one.",
    );
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Sign out everywhere' }),
    );

    await waitFor(() => expect(router.state.location.pathname).toBe('/signin'));
    expect(post).toHaveBeenCalledWith('/api/auth/signout-everywhere');
  });

  it('stays signed in when the member backs out of Sign out everywhere', async () => {
    serve(SIGNED_IN);
    const router = renderAccount();
    await ready();

    fireEvent.click(
      screen.getByRole('button', { name: 'Sign out everywhere' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Keep me signed in' }));

    expect(post).not.toHaveBeenCalled();
    expect(router.state.location.pathname).toBe('/account');
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });
});
