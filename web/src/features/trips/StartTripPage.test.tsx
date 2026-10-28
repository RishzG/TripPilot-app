import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { buildRoutes } from '../../app/router';
import { api } from '../../lib/api';
import { StartTripPage } from './StartTripPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;

function reply(status: number, data?: unknown) {
  return { data, response: { ok: status < 400, status } as Response };
}

function renderStartPage() {
  const router = createMemoryRouter(
    [
      { path: '/trips/new', element: <StartTripPage /> },
      { path: '/trips/:tripId', element: <p>Trip page for the new trip</p> },
    ],
    { initialEntries: ['/trips/new'] },
  );
  return render(<RouterProvider router={router} />);
}

function typeName(value: string) {
  fireEvent.change(screen.getByLabelText('Trip name'), { target: { value } });
}

function submit() {
  fireEvent.click(screen.getByRole('button', { name: 'Start the trip' }));
}

describe('StartTripPage', () => {
  beforeEach(() => {
    post.mockReset();
  });

  it('posts the trip name and opens the new trip', async () => {
    post.mockResolvedValue(reply(201, { id: 'trip-1', name: 'Tahoe weekend' }));
    renderStartPage();
    typeName('Tahoe weekend');
    submit();
    expect(await screen.findByText('Trip page for the new trip')).toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith('/api/trips', {
      body: { name: 'Tahoe weekend' },
    });
  });

  it('rejects an empty name in plain language without calling the API', async () => {
    renderStartPage();
    submit();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(
      'Give your trip a name to get started.',
    );
    expect(post).not.toHaveBeenCalled();
  });

  it('treats a name of only spaces as empty', async () => {
    renderStartPage();
    typeName('   ');
    submit();
    expect((await screen.findByRole('alert')).textContent).toContain(
      'Give your trip a name to get started.',
    );
    expect(post).not.toHaveBeenCalled();
  });

  it('rejects a name over 80 characters without calling the API', async () => {
    renderStartPage();
    typeName('x'.repeat(81));
    submit();
    expect((await screen.findByRole('alert')).textContent).toContain(
      'Keep it under 80 characters.',
    );
    expect(post).not.toHaveBeenCalled();
  });

  it('says nothing was changed and re-enables the button when the API fails', async () => {
    post.mockResolvedValue(reply(500, { detail: 'boom' }));
    renderStartPage();
    typeName('Tahoe weekend');
    submit();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(
      "Couldn't save that. Nothing was changed, so try again.",
    );
    await waitFor(() => {
      const button = screen.getByRole('button', {
        name: 'Start the trip',
      }) as HTMLButtonElement;
      expect(button.disabled).toBe(false);
    });
  });

  it('is reachable at /trips/new through the app router, inside the shell', async () => {
    const router = createMemoryRouter(buildRoutes(), {
      initialEntries: ['/trips/new'],
    });
    get.mockResolvedValue({
      error: { detail: 'Not signed in' },
      response: { ok: false, status: 401 } as Response,
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByRole('heading', { name: 'Start a trip' }),
    ).toBeTruthy();
    expect(screen.getByText('Sandbox — no real money')).toBeTruthy();
  });
});
