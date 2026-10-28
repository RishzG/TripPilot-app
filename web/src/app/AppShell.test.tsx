import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { SandboxBanner } from '../components/SandboxBanner';
import { api } from '../lib/api';
import { buildRoutes } from './router';

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const BANNER_TEXT = 'Sandbox — no real money';

function answer(status: number, data?: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

function signedOut() {
  get.mockImplementation(async (path: string) =>
    path === '/api/me'
      ? answer(401, { detail: 'Not signed in' })
      : answer(404, { detail: 'Not Found' }),
  );
}

function signedInAs(kind: 'member' | 'persona') {
  get.mockImplementation(async (path: string) => {
    if (path === '/api/me') {
      return answer(200, {
        id: 'me-1',
        display_name: 'Maya',
        nickname: null,
        avatar_kind: 'initials',
        avatar_key: null,
        kind,
        is_persona: kind === 'persona',
      });
    }
    if (path === '/api/trips') {
      return answer(200, []);
    }
    return answer(404, { detail: 'Not Found' });
  });
}

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const memoryRouter = createMemoryRouter(buildRoutes(), {
    initialEntries: [path],
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={memoryRouter} />
    </QueryClientProvider>,
  );
}

describe('AppShell sandbox banner', () => {
  beforeEach(() => {
    get.mockReset();
    signedOut();
  });

  it('shows the sandbox banner at the index route', async () => {
    renderAt('/');
    expect(await screen.findByText(BANNER_TEXT)).toBeTruthy();
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Plan the trip. Split it fairly.',
      }),
    ).toBeTruthy();
  });

  it('shows the sandbox banner on an unknown path, with a not-found element inside the shell', async () => {
    renderAt('/no/such/page');
    expect(await screen.findByText(BANNER_TEXT)).toBeTruthy();
    expect(screen.getByText('Page not found')).toBeTruthy();
  });

  it('renders the banner above the page content', async () => {
    renderAt('/');
    const banner = await screen.findByText(BANNER_TEXT);
    const main = screen.getByRole('main');
    expect(
      banner.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('exposes the banner as the only status region', async () => {
    renderAt('/');
    const status = await screen.findByRole('status');
    expect(status.textContent).toBe(BANNER_TEXT);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });
});

describe('AppShell demo persona badge', () => {
  beforeEach(() => get.mockReset());

  it('shows Demo persona when /api/me reports a persona', async () => {
    signedInAs('persona');
    renderAt('/');
    expect(await screen.findByText('Demo persona')).toBeTruthy();
  });

  it('shows no badge for a real member', async () => {
    signedInAs('member');
    renderAt('/');
    await screen.findByRole('heading', { level: 1, name: 'My trips' });
    expect(screen.queryByText('Demo persona')).toBeNull();
  });

  it('shows no badge when signed out', async () => {
    signedOut();
    renderAt('/');
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByText('Demo persona')).toBeNull();
  });

  it('shows the badge on every screen, not just the home page', async () => {
    signedInAs('persona');
    renderAt('/no/such/page');
    expect(await screen.findByText('Demo persona')).toBeTruthy();
  });
});

describe('SandboxBanner colours', () => {
  it('uses theme token classes only, with no colour literal', () => {
    render(<SandboxBanner />);
    const banner = screen.getByRole('status');
    expect(banner.className).toContain('bg-sandbox-banner');
    expect(banner.className).toContain('text-sandbox-banner-foreground');
    expect(banner.getAttribute('style')).toBeNull();
    expect(banner.className).not.toMatch(/#[0-9a-fA-F]{3,8}|rgb|hsl|\[#/);
  });
});
