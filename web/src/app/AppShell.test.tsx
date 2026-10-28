import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { SandboxBanner } from '../components/SandboxBanner';
import { buildRoutes } from './router';

const BANNER_TEXT = 'Sandbox — no real money';

function renderAt(path: string) {
  const memoryRouter = createMemoryRouter(buildRoutes(), {
    initialEntries: [path],
  });
  return render(<RouterProvider router={memoryRouter} />);
}

describe('AppShell sandbox banner', () => {
  it('shows the sandbox banner at the index route', async () => {
    renderAt('/');
    expect(await screen.findByText(BANNER_TEXT)).toBeTruthy();
    expect(screen.getByText('TripPilot')).toBeTruthy();
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

  it('exposes the banner as a status region', async () => {
    renderAt('/');
    const status = await screen.findByRole('status');
    expect(status.textContent).toBe(BANNER_TEXT);
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
