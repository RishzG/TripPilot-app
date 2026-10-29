import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { toast } from 'sonner';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { FakeEventSource } from '../../test-support/fakeEventSource';
import { TripPage } from './TripPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});
vi.mock('sonner', () => ({ toast: vi.fn() }));

interface SaveButtonProps {
  setupTokenPath: string;
  paymentTokenPath: string;
  onSaved: () => void;
  onFailed: (reason: 'cancelled' | 'error') => void;
}

// Stand-in for the PayPal SDK control: the banner hosts it, tests press its outcomes.
vi.mock('../paypal/SavePayPalButton', () => ({
  SavePayPalButton: (props: SaveButtonProps) => (
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

const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;

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

function serve(mock: Mock, routes: Record<string, Reply>) {
  mock.mockImplementation(async (path: string) =>
    answer(routes[path] ?? { status: 404, data: { detail: 'Not Found' } }),
  );
}

const INVITE_URL = 'https://trippilot.test/join/abc123';

interface MemberFixture {
  account_id: string;
  display_name: string;
  nickname: string | null;
  avatar_kind: string;
  avatar_key: string | null;
  role: string;
}

const ORGANISER_TRIP = {
  id: 'trip-1',
  name: 'Tahoe weekend',
  is_organiser: true,
  joining_closed: false,
  members: [
    {
      account_id: 'a1',
      display_name: 'Maya',
      nickname: null,
      avatar_kind: 'initials',
      avatar_key: null,
      role: 'organiser',
    },
    {
      account_id: 'a2',
      display_name: 'Theo',
      nickname: null,
      avatar_kind: 'initials',
      avatar_key: null,
      role: 'member',
    },
  ] as MemberFixture[],
  removed_members: [] as { account_id: string; display_name: string }[],
};

const MEMBER_TRIP = {
  ...ORGANISER_TRIP,
  is_organiser: false,
  removed_members: null,
};

const GET_ROUTES: Record<string, Reply> = {
  '/api/trips/{trip_id}': { status: 200, data: ORGANISER_TRIP },
  '/api/trips/{trip_id}/invite': { status: 200, data: { url: INVITE_URL } },
};

function renderTrip() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/trips/:tripId', element: <TripPage /> },
      { path: '/', element: <p>My trips home</p> },
    ],
    { initialEntries: ['/trips/trip-1'] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function trip(overrides: Partial<typeof ORGANISER_TRIP>) {
  return { status: 200, data: { ...ORGANISER_TRIP, ...overrides } };
}

describe('TripPage basics', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    vi.mocked(toast).mockReset();
  });

  it('shows the trip name and one row per member with the organiser marked', async () => {
    serve(get, GET_ROUTES);
    renderTrip();
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' }),
    ).toBeTruthy();
    const list = screen.getByRole('list', { name: "Who's in" });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain('Maya');
    expect(rows[0]?.textContent).toContain('Organiser');
    expect(rows[1]?.textContent).toContain('Theo');
    expect(rows[1]?.textContent).not.toContain('Organiser');
    expect(get).toHaveBeenCalledWith('/api/trips/{trip_id}', {
      params: { path: { trip_id: 'trip-1' } },
    });
  });

  it('shows how many people are in', async () => {
    serve(get, GET_ROUTES);
    renderTrip();
    expect(await screen.findByText('2 of 12 in')).toBeTruthy();
  });

  it('offers a retry when the trip cannot be loaded', async () => {
    serve(get, { '/api/trips/{trip_id}': { status: 404, data: {} } });
    renderTrip();
    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry loading' })).toBeTruthy();
  });

  it('shows the plan placeholder card in its empty state', async () => {
    serve(get, GET_ROUTES);
    renderTrip();
    expect(
      await screen.findByText(
        'Your plan will appear here once the group starts planning',
      ),
    ).toBeTruthy();
    expect(screen.getByText('Nobody pays anything yet.')).toBeTruthy();
  });

  it('shows the locked empty state when the organiser is alone', async () => {
    serve(get, {
      ...GET_ROUTES,
      '/api/trips/{trip_id}': trip({
        members: [
          {
            account_id: 'a1',
            display_name: 'Maya',
            nickname: null,
            avatar_kind: 'initials',
            avatar_key: null,
            role: 'organiser',
          },
        ],
      }),
    });
    renderTrip();
    expect(
      await screen.findByRole('heading', {
        name: 'Just you so far. Send the invite!',
      }),
    ).toBeTruthy();
    expect(
      screen.getByText('Copy the invite and drop it in your group chat.'),
    ).toBeTruthy();
    expect(screen.getByText('1 of 12 in')).toBeTruthy();
  });
});

describe('TripPage organiser invite card', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    vi.mocked(toast).mockReset();
    serve(get, GET_ROUTES);
  });

  it('shows the link in a read-only field with the locked buttons', async () => {
    renderTrip();
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Invite link' }),
    ).toBeTruthy();
    const field = (await screen.findByLabelText(
      'Invite link address',
    )) as HTMLInputElement;
    await waitFor(() => expect(field.value).toBe(INVITE_URL));
    expect(field.readOnly).toBe(true);
    expect(
      screen.getByRole('button', { name: 'Copy invite link' }),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset link' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Close joining' })).toBeTruthy();
  });

  it('copies the link and says so in a toast', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    renderTrip();
    const copy = await screen.findByRole('button', {
      name: 'Copy invite link',
    });
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Invite link address') as HTMLInputElement)
          .value,
      ).toBe(INVITE_URL),
    );
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(INVITE_URL));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        'Copy the invite and drop it in your group chat',
      ),
    );
  });

  it('falls back to press-and-hold when the clipboard refuses', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    renderTrip();
    const copy = await screen.findByRole('button', {
      name: 'Copy invite link',
    });
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Invite link address') as HTMLInputElement)
          .value,
      ).toBe(INVITE_URL),
    );
    fireEvent.click(copy);
    expect(
      await screen.findByText('Press and hold to copy the link.'),
    ).toBeTruthy();
    expect(toast).not.toHaveBeenCalled();
  });

  it('resets the link in two steps and shows the new one', async () => {
    post.mockResolvedValue(
      answer({
        status: 200,
        data: { url: 'https://trippilot.test/join/fresh999' },
      }),
    );
    renderTrip();
    fireEvent.click(await screen.findByRole('button', { name: 'Reset link' }));
    expect(
      screen.getByText('Reset? The old link stops working right away.'),
    ).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Yes, reset' }));
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Invite link address') as HTMLInputElement)
          .value,
      ).toBe('https://trippilot.test/join/fresh999'),
    );
    expect(post).toHaveBeenCalledWith('/api/trips/{trip_id}/invite/reset', {
      params: { path: { trip_id: 'trip-1' } },
    });
    expect(screen.getByRole('button', { name: 'Reset link' })).toBeTruthy();
  });

  it('keeps the old link when the organiser backs out of a reset', async () => {
    renderTrip();
    fireEvent.click(await screen.findByRole('button', { name: 'Reset link' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep old link' }));
    expect(screen.getByRole('button', { name: 'Reset link' })).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it('closes and reopens joining with a caption showing the state', async () => {
    post
      .mockResolvedValueOnce(
        answer({ status: 200, data: { joining_closed: true } }),
      )
      .mockResolvedValueOnce(
        answer({ status: 200, data: { joining_closed: false } }),
      );
    renderTrip();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Close joining' }),
    );
    expect(
      await screen.findByText(
        'Joining is closed. Nobody new can use the link.',
      ),
    ).toBeTruthy();
    expect(post).toHaveBeenCalledWith('/api/trips/{trip_id}/joining', {
      params: { path: { trip_id: 'trip-1' } },
      body: { closed: true },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Open joining' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Close joining' }),
      ).toBeTruthy(),
    );
    expect(
      screen.queryByText('Joining is closed. Nobody new can use the link.'),
    ).toBeNull();
  });

  it('is not shown to a member who is not the organiser', async () => {
    serve(get, {
      ...GET_ROUTES,
      '/api/trips/{trip_id}': { status: 200, data: MEMBER_TRIP },
    });
    renderTrip();
    await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' });
    expect(screen.queryByRole('heading', { name: 'Invite link' })).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Copy invite link' }),
    ).toBeNull();
    expect(screen.queryByRole('button', { name: /^Remove/ })).toBeNull();
    expect(get).not.toHaveBeenCalledWith(
      '/api/trips/{trip_id}/invite',
      expect.anything(),
    );
  });
});

describe('TripPage membership controls', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    vi.mocked(toast).mockReset();
    serve(get, GET_ROUTES);
  });

  it('removes a member after an inline confirm and explains it sticks', async () => {
    post.mockResolvedValue(
      answer({ status: 200, data: { account_id: 'a2', status: 'removed' } }),
    );
    renderTrip();
    expect(screen.queryByRole('button', { name: 'Remove Maya' })).toBeNull();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Theo' }));
    expect(screen.getByText('Remove Theo?')).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Yes, remove' }));
    expect(
      await screen.findByText(
        "Theo can't rejoin from the invite link unless you add them back.",
      ),
    ).toBeTruthy();
    expect(post).toHaveBeenCalledWith(
      '/api/trips/{trip_id}/members/{account_id}/remove',
      { params: { path: { trip_id: 'trip-1', account_id: 'a2' } } },
    );
    expect(
      screen.getByRole('heading', { level: 2, name: 'Removed' }),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add back' })).toBeTruthy();
    expect(screen.getByText('1 of 12 in')).toBeTruthy();
  });

  it('keeps the member when the organiser changes their mind', async () => {
    renderTrip();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Theo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep Theo' }));
    expect(screen.getByRole('button', { name: 'Remove Theo' })).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it('puts the Remove button back after six seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderTrip();
      fireEvent.click(
        await screen.findByRole('button', { name: 'Remove Theo' }),
      );
      expect(screen.getByText('Remove Theo?')).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(6100);
      });
      expect(screen.queryByText('Remove Theo?')).toBeNull();
      expect(screen.getByRole('button', { name: 'Remove Theo' })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('lists removed members and adds one back', async () => {
    serve(get, {
      ...GET_ROUTES,
      '/api/trips/{trip_id}': trip({
        removed_members: [{ account_id: 'a3', display_name: 'Rae' }],
      }),
    });
    post.mockResolvedValue(
      answer({ status: 200, data: { account_id: 'a3', status: 'active' } }),
    );
    renderTrip();
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Removed' }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add back' }));
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Removed' })).toBeNull(),
    );
    expect(post).toHaveBeenCalledWith(
      '/api/trips/{trip_id}/members/{account_id}/readd',
      { params: { path: { trip_id: 'trip-1', account_id: 'a3' } } },
    );
    const list = screen.getByRole('list', { name: "Who's in" });
    expect(within(list).getByText('Rae')).toBeTruthy();
    expect(screen.getByText('3 of 12 in')).toBeTruthy();
  });

  it('shows a plain retry message when a membership action fails', async () => {
    post.mockResolvedValue(answer({ status: 500, data: {} }));
    renderTrip();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Theo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, remove' }));
    expect(
      await screen.findByText(
        "Couldn't save that. Nothing was changed, so try again.",
      ),
    ).toBeTruthy();
    expect(screen.getByText('2 of 12 in')).toBeTruthy();
  });

  it('lets a member leave after an inline confirm and returns to My trips', async () => {
    serve(get, {
      ...GET_ROUTES,
      '/api/trips/{trip_id}': { status: 200, data: MEMBER_TRIP },
    });
    post.mockResolvedValue(
      answer({ status: 200, data: { account_id: 'a2', status: 'left' } }),
    );
    const router = renderTrip();
    fireEvent.click(await screen.findByRole('button', { name: 'Leave trip' }));
    expect(screen.getByText('Leave Tahoe weekend?')).toBeTruthy();
    expect(
      screen.getByText("You'll need a new invite to come back."),
    ).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Leave trip' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
    expect(post).toHaveBeenCalledWith('/api/trips/{trip_id}/leave', {
      params: { path: { trip_id: 'trip-1' } },
    });
  });

  it('does not offer the organiser a Leave button', async () => {
    renderTrip();
    await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' });
    expect(screen.queryByRole('button', { name: 'Leave trip' })).toBeNull();
  });
});

describe('TripPage live updates', () => {
  const SAM = {
    account_id: 'a3',
    display_name: 'Sam',
    nickname: null,
    avatar_kind: 'initials',
    avatar_key: null,
    role: 'member',
  };

  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    FakeEventSource.reset();
    vi.stubGlobal('EventSource', FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stream(): FakeEventSource {
    const source = FakeEventSource.instances[0];
    if (source === undefined) {
      throw new Error('the trip page did not open its event stream');
    }
    return source;
  }

  async function renderWithSamJoiningLater() {
    let samIn = false;
    get.mockImplementation(async (path: string) => {
      if (path === '/api/trips/{trip_id}') {
        const members = samIn
          ? [...ORGANISER_TRIP.members, SAM]
          : ORGANISER_TRIP.members;
        return answer({ status: 200, data: { ...ORGANISER_TRIP, members } });
      }
      return answer({ status: 200, data: { url: INVITE_URL } });
    });
    renderTrip();
    await screen.findByText('2 of 12 in');
    return () => {
      samIn = true;
      act(() => stream().emit('member.joined', '{"account_id":"a3"}'));
    };
  }

  it('opens the trip event stream for the trip being shown', async () => {
    await renderWithSamJoiningLater();
    expect(stream().url).toBe('/api/trips/trip-1/events');
  });

  it('adds a member who joins without a refresh, animated and announced', async () => {
    const samJoins = await renderWithSamJoiningLater();
    const list = screen.getByRole('list', { name: "Who's in" });
    const firstPaint = within(list).getAllByRole('listitem');
    for (const row of firstPaint) {
      expect(row.className).not.toContain('animate-in');
    }

    samJoins();

    expect(await screen.findByText('3 of 12 in')).toBeTruthy();
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[2]?.textContent).toContain('Sam');
    expect(rows[2]?.className).toContain('motion-safe:animate-in');
    expect(rows[0]?.className).not.toContain('animate-in');
    expect(
      screen.getByText('Sam joined the trip').closest('[aria-live]'),
    ).not.toBeNull();
  });
});

describe('TripPage save-PayPal banner', () => {
  const BANNER = 'Save PayPal so you can commit in one tap';
  const DISMISSED_KEY = 'tp-save-banner-dismissed:trip-1';
  const ME = {
    id: 'me-1',
    display_name: 'Jo',
    nickname: null,
    avatar_kind: 'initials',
    avatar_key: null,
    kind: 'member',
    is_persona: false,
  };
  const BANNER_ROUTES: Record<string, Reply> = {
    ...GET_ROUTES,
    '/api/me': { status: 200, data: ME },
    '/api/paypal/vault/status': { status: 200, data: { saved: false } },
  };

  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    localStorage.clear();
    vi.mocked(toast).mockReset();
  });

  it('shows a quiet banner with the save control to a member who skipped saving', async () => {
    serve(get, BANNER_ROUTES);
    renderTrip();

    expect(await screen.findByText(BANNER)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'sdk-saved' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeTruthy();
  });

  it('never shows the banner when PayPal is already saved', async () => {
    serve(get, {
      ...BANNER_ROUTES,
      '/api/paypal/vault/status': { status: 200, data: { saved: true } },
    });
    renderTrip();

    await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' });
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith('/api/paypal/vault/status'),
    );
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('says nothing when the saved status cannot be read', async () => {
    serve(get, {
      ...BANNER_ROUTES,
      '/api/paypal/vault/status': { status: 500, data: { detail: 'boom' } },
    });
    renderTrip();

    await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' });
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith('/api/paypal/vault/status'),
    );
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('does not show a demo persona the banner', async () => {
    serve(get, {
      ...BANNER_ROUTES,
      '/api/me': {
        status: 200,
        data: { ...ME, kind: 'persona', is_persona: true },
      },
    });
    renderTrip();

    await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' });
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/me'));
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('stays hidden after Dismiss, across reloads, for this trip only', async () => {
    serve(get, BANNER_ROUTES);
    renderTrip();
    await screen.findByText(BANNER);

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

    expect(screen.queryByText(BANNER)).toBeNull();
    expect(localStorage.getItem(DISMISSED_KEY)).not.toBeNull();
    expect(localStorage.getItem('tp-save-banner-dismissed:trip-2')).toBeNull();
    cleanup();

    renderTrip();
    await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' });
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith('/api/paypal/vault/status'),
    );
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('hides the banner once PayPal is saved from it', async () => {
    serve(get, BANNER_ROUTES);
    renderTrip();
    await screen.findByText(BANNER);

    serve(get, {
      ...BANNER_ROUTES,
      '/api/paypal/vault/status': { status: 200, data: { saved: true } },
    });
    fireEvent.click(screen.getByRole('button', { name: 'sdk-saved' }));

    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
  });

  it('tells the member plainly when saving from the banner fails', async () => {
    serve(get, BANNER_ROUTES);
    renderTrip();
    await screen.findByText(BANNER);

    fireEvent.click(screen.getByRole('button', { name: 'sdk-failed' }));

    expect(
      await screen.findByText(
        "Couldn't save that. Nothing was changed, so try again.",
      ),
    ).toBeTruthy();
    expect(screen.getByText(BANNER)).toBeTruthy();
  });
});

describe('TripPage member avatars', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('shows each member with their avatar and nickname, never a saved-PayPal marker', async () => {
    serve(get, {
      ...GET_ROUTES,
      '/api/trips/{trip_id}': trip({
        members: [
          {
            account_id: 'a1',
            display_name: 'Maya Rao',
            nickname: 'Maya',
            avatar_kind: 'illustrated',
            avatar_key: 'maya',
            role: 'organiser',
          },
          {
            account_id: 'a2',
            display_name: 'Theo Park',
            nickname: null,
            avatar_kind: 'initials',
            avatar_key: null,
            role: 'member',
          },
        ],
      }),
    });
    renderTrip();

    const list = await screen.findByRole('list', { name: "Who's in" });
    const rows = within(list).getAllByRole('listitem');
    expect(rows[0]?.textContent).toContain('Maya');
    expect(rows[0]?.textContent).not.toContain('Maya Rao');
    const image = rows[0]?.querySelector('img');
    expect(image?.getAttribute('alt')).toBe('');
    expect(image?.getAttribute('src')).toContain('maya');
    expect(rows[1]?.textContent).toContain('Theo Park');
    expect(rows[1]?.querySelector('img')).toBeNull();
    expect(rows[1]?.textContent).toContain('TP');
    expect(list.textContent?.toLowerCase()).not.toContain('paypal');
  });
});
