import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { PersonaPickerPage } from './PersonaPickerPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;

function reply(status: number, data?: unknown) {
  return { data, response: { ok: status < 400, status } as Response };
}

const PERSONAS = [
  { slug: 'maya', name: 'Maya', avatar_key: 'maya', note: 'plans everything' },
  { slug: 'theo', name: 'Theo', avatar_key: 'theo', note: 'always late' },
];

function renderPicker() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/demo', element: <PersonaPickerPage /> },
      { path: '/trips/new', element: <p>Start a trip screen</p> },
    ],
    { initialEntries: ['/demo'] },
  );
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('PersonaPickerPage', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('lists each persona with a Continue button and their note', async () => {
    get.mockResolvedValue(reply(200, PERSONAS));
    renderPicker();
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Try the demo' }),
    ).toBeTruthy();
    expect(screen.getByText('plans everything')).toBeTruthy();
    expect(
      screen.getByRole('button', { name: 'Continue as Maya' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', { name: 'Continue as Theo' }),
    ).toBeTruthy();
  });

  it('signs in as the chosen persona and goes to start a trip', async () => {
    get.mockResolvedValue(reply(200, PERSONAS));
    post.mockResolvedValue(reply(200, { id: 'a1' }));
    renderPicker();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Continue as Maya' }),
    );
    expect(await screen.findByText('Start a trip screen')).toBeTruthy();
    expect(post).toHaveBeenCalledWith('/api/demo/personas/{slug}/session', {
      params: { path: { slug: 'maya' } },
    });
  });

  it('renders the standard not-found page when the persona list is a 404 (demo mode off, D-15)', async () => {
    get.mockResolvedValue(reply(404, { detail: 'Not Found' }));
    renderPicker();
    expect(
      await screen.findByRole('heading', { name: "We can't find that page." }),
    ).toBeTruthy();
    expect(screen.getByText('The link may be old.')).toBeTruthy();
    const link = screen.getByRole('link', { name: 'Go to My trips' });
    expect(link.getAttribute('href')).toBe('/');
    expect(screen.queryByText('Demo mode is off')).toBeNull();
  });

  it('renders the standard not-found page for an empty persona list', async () => {
    get.mockResolvedValue(reply(200, []));
    renderPicker();
    expect(
      await screen.findByRole('heading', { name: "We can't find that page." }),
    ).toBeTruthy();
  });
});
