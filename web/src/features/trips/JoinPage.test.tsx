import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { JoinPage } from './JoinPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;

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

const PREVIEW: Reply = {
  status: 200,
  data: {
    trip_name: 'Tahoe weekend',
    organiser_name: 'Olivia Organiser',
    members: ['Olivia Organiser'],
    joining_open: true,
    already_member: false,
    trip_id: null,
  },
};
const SIGNED_OUT: Reply = { status: 401, data: { detail: 'Not signed in' } };
const ME: Reply = {
  status: 200,
  data: {
    id: 'me-1',
    display_name: 'Jo Joiner',
    nickname: null,
    avatar_kind: 'initials',
    avatar_key: null,
    kind: 'member',
    is_persona: false,
  },
};

function renderJoin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/join/:token', element: <JoinPage /> },
      { path: '/trips/:tripId', element: <p>Trip page for the group</p> },
      { path: '/', element: <p>My trips home</p> },
    ],
    { initialEntries: ['/join/tok-123'] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe('JoinPage signed out', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('invites the visitor by organiser first name and trip, with a sign-in link back here', async () => {
    serve({
      '/api/me': SIGNED_OUT,
      '/api/invites/{token}': {
        status: 200,
        data: {
          ...(PREVIEW.data as object),
          organiser_name: 'Olivia',
          members: [],
        },
      },
    });
    renderJoin();
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Olivia invited you to Tahoe weekend',
      }),
    ).toBeTruthy();
    expect(screen.getByText("Sign in to join and see who's in.")).toBeTruthy();
    const signIn = screen.getByRole('link', { name: 'Sign in to join' });
    expect(signIn.getAttribute('href')).toBe(
      `/signin?next=${encodeURIComponent('/join/tok-123')}`,
    );
  });

  it('offers a demo friend sign-in only when the demo personas exist', async () => {
    serve({
      '/api/me': SIGNED_OUT,
      '/api/invites/{token}': PREVIEW,
      '/api/demo/personas': { status: 200, data: [{ slug: 'sam' }] },
    });
    renderJoin();
    const demo = await screen.findByRole('link', {
      name: 'Join as a demo friend',
    });
    expect(demo.getAttribute('href')).toBe(
      `/demo?next=${encodeURIComponent('/join/tok-123')}`,
    );
  });

  it('shows no demo option when the persona list is a 404', async () => {
    serve({ '/api/me': SIGNED_OUT, '/api/invites/{token}': PREVIEW });
    renderJoin();
    await screen.findByRole('link', { name: 'Sign in to join' });
    expect(
      screen.queryByRole('link', { name: 'Join as a demo friend' }),
    ).toBeNull();
  });
});

describe('JoinPage signed in', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('shows the confirm card with the organiser and who is in', async () => {
    serve({
      '/api/me': ME,
      '/api/invites/{token}': {
        status: 200,
        data: {
          ...(PREVIEW.data as object),
          members: ['Olivia Organiser', 'Sam'],
        },
      },
    });
    renderJoin();
    expect(
      await screen.findByRole('heading', { name: 'Join Tahoe weekend?' }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'Olivia Organiser is organising. In so far: Olivia Organiser, Sam.',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Join trip' })).toBeTruthy();
    const decline = screen.getByRole('link', { name: 'Decline invite' });
    expect(decline.getAttribute('href')).toBe('/');
  });

  it('joins with one tap and goes to the trip page', async () => {
    serve({ '/api/me': ME, '/api/invites/{token}': PREVIEW });
    post.mockResolvedValue(
      reply({
        status: 200,
        data: { trip_id: 'trip-9', already_member: false },
      }),
    );
    const router = renderJoin();
    fireEvent.click(await screen.findByRole('button', { name: 'Join trip' }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/trips/trip-9'),
    );
    expect(post).toHaveBeenCalledWith('/api/invites/{token}/join', {
      params: { path: { token: 'tok-123' } },
    });
    expect(await screen.findByText('Trip page for the group')).toBeTruthy();
  });

  it('sends an existing member straight to the trip', async () => {
    serve({
      '/api/me': ME,
      '/api/invites/{token}': {
        status: 200,
        data: {
          ...(PREVIEW.data as object),
          already_member: true,
          trip_id: 'trip-4',
        },
      },
    });
    const router = renderJoin();
    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/trips/trip-4'),
    );
    expect(post).not.toHaveBeenCalled();
  });

  it.each([
    [
      'removed',
      "You can't join this trip",
      'The organiser removed you from this trip. Ask them to add you back.',
    ],
    ['full', 'This trip is full', 'It already has 12 people.'],
    ['closed', 'Joining is closed', 'Ask the organiser to open it again.'],
  ])('explains a 409 %s answer', async (reason, heading, body) => {
    serve({ '/api/me': ME, '/api/invites/{token}': PREVIEW });
    post.mockResolvedValue(reply({ status: 409, data: { detail: reason } }));
    renderJoin();
    fireEvent.click(await screen.findByRole('button', { name: 'Join trip' }));
    expect(await screen.findByRole('heading', { name: heading })).toBeTruthy();
    expect(screen.getByText(body)).toBeTruthy();
  });

  it('says the link is not working when the preview is a 404', async () => {
    serve({ '/api/me': ME });
    renderJoin();
    expect(
      await screen.findByRole('heading', {
        name: "This invite link isn't working",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'It may have been reset. Ask the organiser for a new one.',
      ),
    ).toBeTruthy();
  });

  it('offers a retry when the preview cannot be loaded', async () => {
    serve({ '/api/me': ME, '/api/invites/{token}': { status: 500, data: {} } });
    renderJoin();
    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry loading' })).toBeTruthy();
  });

  it('shows the plain retry copy when joining fails for another reason', async () => {
    serve({ '/api/me': ME, '/api/invites/{token}': PREVIEW });
    post.mockResolvedValue(reply({ status: 500, data: {} }));
    renderJoin();
    fireEvent.click(await screen.findByRole('button', { name: 'Join trip' }));
    expect(
      await screen.findByText(
        "Couldn't save that. Nothing was changed, so try again.",
      ),
    ).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Join trip' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
});
