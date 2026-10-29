import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
const post = api.POST as unknown as Mock;

// Radix popper (the account menu) measures its trigger with ResizeObserver, which jsdom lacks.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
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

describe('AppShell header', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('puts the skip link first, then the banner, header and main', async () => {
    signedOut();
    renderAt('/');
    const skip = await screen.findByRole('link', { name: 'Skip to content' });
    expect(skip.getAttribute('href')).toBe('#main');
    const banner = screen.getByRole('status');
    const header = screen.getByRole('banner');
    const main = screen.getByRole('main');
    expect(main.getAttribute('id')).toBe('main');
    expect(
      skip.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      banner.compareDocumentPosition(header) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      header.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('names the logo link and keeps one wordmark that assistive technology skips', async () => {
    signedOut();
    renderAt('/');
    const logo = await screen.findByRole('link', {
      name: 'TripPilot, my trips',
    });
    expect(logo.getAttribute('href')).toBe('/');
    const wordmark = screen.getByText('TripPilot');
    expect(wordmark.getAttribute('aria-hidden')).toBe('true');
  });

  it('shows a Sign in link instead of the account menu when signed out', async () => {
    signedOut();
    renderAt('/');
    const link = await screen.findByRole('link', { name: 'Sign in' });
    expect(link.getAttribute('href')).toBe('/signin');
    expect(screen.queryByRole('button', { name: 'Account menu' })).toBeNull();
  });

  it('falls back to Sign in when /api/me fails for a reason other than 401', async () => {
    get.mockImplementation(async () => answer(500, { detail: 'boom' }));
    renderAt('/no/such/page');
    expect(await screen.findByRole('link', { name: 'Sign in' })).toBeTruthy();
    expect(screen.getByText('Page not found')).toBeTruthy();
  });

  it('opens an account menu with Account, My trips and Sign out when signed in', async () => {
    signedInAs('member');
    renderAt('/');
    const button = await screen.findByRole('button', { name: 'Account menu' });
    expect(button.getAttribute('aria-haspopup')).toBe('menu');
    fireEvent.keyDown(button, { key: 'Enter' });
    const account = await screen.findByRole('menuitem', { name: 'Account' });
    expect(account.getAttribute('href')).toBe('/account');
    expect(
      screen.getByRole('menuitem', { name: 'My trips' }).getAttribute('href'),
    ).toBe('/');
    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Sign in' })).toBeNull();
  });

  it('signs out from the menu and lands on the sign-in page', async () => {
    signedInAs('member');
    post.mockResolvedValue({ response: { ok: true, status: 204 } as Response });
    renderAt('/');
    const button = await screen.findByRole('button', { name: 'Account menu' });
    fireEvent.keyDown(button, { key: 'Enter' });
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/auth/signout'));
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Sign in to TripPilot',
      }),
    ).toBeTruthy();
  });
});

describe('AppShell bottom tab bar', () => {
  beforeEach(() => {
    get.mockReset();
    signedInAs('member');
  });

  it('shows one Trip tab inside a trip route, hidden from md up', async () => {
    renderAt('/trips/trip-1');
    const nav = await screen.findByRole('navigation', { name: 'Trip' });
    expect(nav.className).toContain('md:hidden');
    const tab = screen.getByRole('link', { name: 'Trip' });
    expect(tab.getAttribute('href')).toBe('/trips/trip-1');
    expect(tab.getAttribute('aria-current')).toBe('page');
    expect(tab.className).toContain('min-h-11');
    expect(screen.getByRole('main').className).toContain('pb-24');
  });

  it('is not shown on the start-trip form, the home page or other routes', async () => {
    for (const path of ['/trips/new', '/', '/account']) {
      const view = renderAt(path);
      await screen.findByRole('banner');
      expect(screen.queryByRole('navigation', { name: 'Trip' })).toBeNull();
      view.unmount();
    }
  });
});
