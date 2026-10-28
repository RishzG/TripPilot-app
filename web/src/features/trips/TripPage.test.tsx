import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Mock } from 'vitest';
import { api } from '../../lib/api';
import { TripPage } from './TripPage';

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>();
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } };
});

const get = api.GET as unknown as Mock;

function reply(status: number, data?: unknown) {
  return { data, response: { ok: status < 400, status } as Response };
}

function renderTrip() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [{ path: '/trips/:tripId', element: <TripPage /> }],
    {
      initialEntries: ['/trips/trip-1'],
    },
  );
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('TripPage', () => {
  beforeEach(() => {
    get.mockReset();
  });

  it('shows the trip name and one row per member with the organiser marked', async () => {
    get.mockResolvedValue(
      reply(200, {
        id: 'trip-1',
        name: 'Tahoe weekend',
        is_organiser: true,
        members: [
          { account_id: 'a1', display_name: 'Maya', role: 'organiser' },
          { account_id: 'a2', display_name: 'Theo', role: 'member' },
        ],
      }),
    );
    renderTrip();
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Tahoe weekend' }),
    ).toBeTruthy();
    const rows = screen.getAllByRole('listitem');
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
    get.mockResolvedValue(
      reply(200, {
        id: 'trip-1',
        name: 'Tahoe weekend',
        is_organiser: true,
        members: [
          { account_id: 'a1', display_name: 'Maya', role: 'organiser' },
        ],
      }),
    );
    renderTrip();
    expect(await screen.findByText('1 of 12 in')).toBeTruthy();
  });

  it('offers a retry when the trip cannot be loaded', async () => {
    get.mockResolvedValue(reply(404, { detail: 'Trip not found' }));
    renderTrip();
    expect(await screen.findByText("We couldn't load that.")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry loading' })).toBeTruthy();
  });
});
