import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { PoolBuyersPage } from './PoolBuyersPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;

function answer(status: number, data?: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : data,
    response: { ok: status < 400, status } as Response,
  };
}

const BUYERS = [
  {
    slug: 'maya',
    persona_slug: 'maya',
    sandbox_email: 'sb-maya@personal.example.com',
    status: 'pending',
  },
  {
    slug: 'sam',
    persona_slug: null,
    sandbox_email: null,
    status: 'enrolled',
  },
];

function renderPage() {
  const router = createMemoryRouter(
    [{ path: '/admin/pool', element: <PoolBuyersPage /> }],
    { initialEntries: ['/admin/pool'] },
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe('PoolBuyersPage', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('lists each buyer with its status and an enrol link, never a token', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    renderPage();

    expect(
      await screen.findByText('sb-maya@personal.example.com'),
    ).toBeTruthy();
    expect(screen.getByText('Pending')).toBeTruthy();
    expect(screen.getByText('Enrolled')).toBeTruthy();
    const enrol = screen.getByRole('link', { name: 'Enrol maya' });
    expect(enrol.getAttribute('href')).toBe('/admin/pool/enrol/maya');
    expect(screen.getByRole('link', { name: 'Enrol again sam' })).toBeTruthy();
    expect(get).toHaveBeenCalledWith('/api/paypal/pool/buyers');
  });

  it('shows the empty copy when the pool has no buyers', async () => {
    get.mockResolvedValue(answer(200, []));
    renderPage();
    expect(await screen.findByText('No pool buyers yet.')).toBeTruthy();
  });

  it('posts the new buyer, clears the form and reloads the list', async () => {
    get.mockResolvedValue(answer(200, []));
    post.mockResolvedValue(
      answer(201, {
        slug: 'ana',
        persona_slug: 'ana',
        sandbox_email: 'sb-ana@personal.example.com',
        status: 'pending',
      }),
    );
    renderPage();
    await screen.findByText('No pool buyers yet.');

    fill('Slug', ' ana ');
    fill('Persona slug', 'ana');
    fill('Sandbox email', 'sb-ana@personal.example.com');
    fireEvent.click(screen.getByRole('button', { name: 'Add buyer' }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith('/api/paypal/pool/buyers', {
      body: {
        slug: 'ana',
        persona_slug: 'ana',
        sandbox_email: 'sb-ana@personal.example.com',
      },
    });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect((screen.getByLabelText('Slug') as HTMLInputElement).value).toBe('');
  });

  it('sends null for the optional fields left empty', async () => {
    get.mockResolvedValue(answer(200, []));
    post.mockResolvedValue(
      answer(201, {
        slug: 'ana',
        persona_slug: null,
        sandbox_email: null,
        status: 'pending',
      }),
    );
    renderPage();
    await screen.findByText('No pool buyers yet.');

    fill('Slug', 'ana');
    fireEvent.click(screen.getByRole('button', { name: 'Add buyer' }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith('/api/paypal/pool/buyers', {
      body: { slug: 'ana', persona_slug: null, sandbox_email: null },
    });
  });

  it('explains a duplicate slug in an alert', async () => {
    get.mockResolvedValue(answer(200, BUYERS));
    post.mockResolvedValue(answer(409, { detail: 'slug_taken' }));
    renderPage();
    await screen.findByText('Pending');

    fill('Slug', 'maya');
    fireEvent.click(screen.getByRole('button', { name: 'Add buyer' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('That slug is already in the pool.');
  });

  it('does not call the API for an empty slug', async () => {
    get.mockResolvedValue(answer(200, []));
    renderPage();
    await screen.findByText('No pool buyers yet.');

    fireEvent.click(screen.getByRole('button', { name: 'Add buyer' }));

    expect(post).not.toHaveBeenCalled();
  });

  it('offers a retry when the load fails', async () => {
    get.mockResolvedValueOnce(answer(500, { detail: 'boom' }));
    renderPage();
    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();

    get.mockResolvedValue(answer(200, []));
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }));
    expect(await screen.findByText('No pool buyers yet.')).toBeTruthy();
  });

  it('shows the standard not-found text to someone who is not an admin', async () => {
    get.mockResolvedValue(answer(403, { detail: 'Forbidden' }));
    renderPage();
    expect(await screen.findByText('Page not found')).toBeTruthy();
    expect(screen.queryByText('Pool buyers')).toBeNull();
  });
});
