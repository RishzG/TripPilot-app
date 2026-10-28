import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { HomePage } from './HomePage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;

interface Reply {
  status: number;
  data?: unknown;
}

function serve(routes: Record<string, Reply>) {
  get.mockImplementation(async (path: string) => {
    const { status, data } = routes[path] ?? {
      status: 404,
      data: { detail: 'Not Found' },
    };
    return {
      data: status < 400 ? data : undefined,
      error: status < 400 ? undefined : data,
      response: { ok: status < 400, status } as Response,
    };
  });
}

const SIGNED_OUT: Reply = { status: 401, data: { detail: 'Not signed in' } };
const ME: Reply = {
  status: 200,
  data: {
    id: 'me-1',
    display_name: 'Maya',
    nickname: null,
    avatar_kind: 'illustrated',
    avatar_key: 'maya',
    kind: 'persona',
    is_persona: true,
  },
};

function renderHome() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter([{ path: '/', element: <HomePage /> }], {
    initialEntries: ['/'],
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('HomePage signed out', () => {
  beforeEach(() => get.mockReset());

  it('shows the landing with Start a trip that goes through sign-in', async () => {
    serve({ '/api/me': SIGNED_OUT });
    renderHome();
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Plan the trip. Split it fairly.',
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'Get your group from "we should go somewhere" to booked, without anyone chasing money.',
      ),
    ).toBeTruthy();
    const start = screen.getByRole('link', { name: 'Start a trip' });
    expect(start.getAttribute('href')).toBe(
      `/signin?next=${encodeURIComponent('/trips/new')}`,
    );
  });

  it('offers Try the demo only when the persona list answers 200', async () => {
    serve({
      '/api/me': SIGNED_OUT,
      '/api/demo/personas': { status: 200, data: [{ slug: 'maya' }] },
    });
    renderHome();
    const demo = await screen.findByRole('link', { name: 'Try the demo' });
    expect(demo.getAttribute('href')).toBe('/demo');
  });

  it('hides Try the demo when demo mode is off', async () => {
    serve({ '/api/me': SIGNED_OUT });
    renderHome();
    await screen.findByRole('link', { name: 'Start a trip' });
    expect(screen.queryByRole('link', { name: 'Try the demo' })).toBeNull();
  });
});

describe('HomePage signed in', () => {
  beforeEach(() => get.mockReset());

  it('lists My trips with each trip linking to its page', async () => {
    serve({
      '/api/me': ME,
      '/api/trips': {
        status: 200,
        data: [
          {
            id: 't1',
            name: 'Tahoe weekend',
            role: 'organiser',
            member_count: 3,
            demo_mode: true,
          },
          {
            id: 't2',
            name: 'Lisbon',
            role: 'member',
            member_count: 1,
            demo_mode: true,
          },
        ],
      },
    });
    renderHome();
    expect(
      await screen.findByRole('heading', { level: 1, name: 'My trips' }),
    ).toBeTruthy();
    const tahoe = screen.getByRole('link', { name: /Tahoe weekend/ });
    expect(tahoe.getAttribute('href')).toBe('/trips/t1');
    expect(tahoe.textContent).toContain('3 people');
    expect(tahoe.textContent).toContain('Organiser');
    const lisbon = screen.getByRole('link', { name: /Lisbon/ });
    expect(lisbon.textContent).toContain('1 person');
    expect(lisbon.textContent).not.toContain('Organiser');
    const start = screen.getByRole('link', { name: 'Start a trip' });
    expect(start.getAttribute('href')).toBe('/trips/new');
  });

  it('shows the locked empty state when there are no trips', async () => {
    serve({ '/api/me': ME, '/api/trips': { status: 200, data: [] } });
    renderHome();
    expect(
      await screen.findByRole('heading', { name: 'No trips yet — start one!' }),
    ).toBeTruthy();
    expect(
      screen.getByText('Trips you start or join show up here.'),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Start a trip' })).toBeTruthy();
  });

  it('offers a retry when the trips cannot be loaded', async () => {
    serve({ '/api/me': ME, '/api/trips': { status: 500, data: {} } });
    renderHome();
    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry loading' })).toBeTruthy();
  });
});
