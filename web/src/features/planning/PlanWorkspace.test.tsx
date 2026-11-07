import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import type { Mock } from 'vitest';
import { api } from '@/lib/api';
import { PlanWorkspace } from './PlanWorkspace';

vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() },
}));
const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;
const put = api.PUT as unknown as Mock;
const members = [
  {
    account_id: 'member-1',
    display_name: 'Maya',
    nickname: null,
    avatar_kind: 'initials',
    avatar_key: null,
    role: 'organiser',
  },
];
const context = {
  name: 'Chicago weekend',
  destination: 'Chicago',
  start_date: '2026-11-07',
  end_date: '2026-11-07',
  timezone: 'America/Chicago',
  revision: 3,
};
const item = {
  id: 'item-1',
  title: 'Park walk',
  day: '2026-11-07',
  starts_at: '10:00:00',
  duration_minutes: 60,
  latitude: 41.88,
  longitude: -87.62,
  location: 'Millennium Park',
  total_cents: 101,
  currency: 'USD',
  participants: ['member-1'],
  cost_basis: 'estimate',
  sources: [
    {
      url: 'https://example.com/park',
      label: 'Official park',
      checked_at: '2026-11-06T10:00:00Z',
    },
  ],
};
const version = {
  id: 'version-1',
  title: 'Chicago day',
  sample: false,
  context_revision: 3,
  created_at: '2026-11-06T10:00:00Z',
  items: [item],
  shares: { 'item-1': { 'member-1': 101 } },
  totals: { 'member-1': 101 },
  total_cents: 101,
  current: true,
};
const state = {
  context,
  versions: [version],
  selected_id: null,
  runs: [],
  proposals: [],
  my_explanations: { 'version-1': 'Your private fit explanation' },
  pilot_configured: true,
};
function reply(data: unknown) {
  return { data, response: { ok: true, status: 200 } };
}
function show(organiser = true, data = state) {
  get.mockImplementation(async (path: string) =>
    reply(path === '/api/me' ? { id: 'member-1' } : data),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <PlanWorkspace
        tripId="trip-1"
        isOrganiser={organiser}
        members={members}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  get.mockReset();
  post.mockReset().mockResolvedValue(reply({}));
  put.mockReset().mockResolvedValue(reply(context));
});
afterEach(cleanup);

it('shows sourced day items, exact estimates, an attributed map and only the supplied private explanation', async () => {
  show();
  expect(await screen.findByText('1. Park walk')).toBeTruthy();
  expect(
    screen.getByRole('link', { name: 'Official park' }).getAttribute('href'),
  ).toBe('https://example.com/park');
  expect(
    screen.getByTitle('Itinerary map: Millennium Park').getAttribute('src'),
  ).toContain('openstreetmap.org/export/embed.html');
  expect(screen.getByText('Your private fit explanation')).toBeTruthy();
  expect(
    screen.queryByText('Someone else’s private fit explanation'),
  ).toBeNull();
  expect(screen.getByText(/Estimated itinerary budget/).textContent).toContain(
    '$1.01',
  );
});

it('saves trip context with the revision that was edited', async () => {
  show();
  fireEvent.click(await screen.findByText('Where and when'));
  const destination = await screen.findByLabelText('Destination');
  fireEvent.change(destination, { target: { value: 'Chicago downtown' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save trip details' }));
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/trips/{trip_id}/planning/context', {
      params: { path: { trip_id: 'trip-1' } },
      body: { ...context, destination: 'Chicago downtown' },
    }),
  );
});

it('keeps leader mutation controls away from members', async () => {
  show(false);
  await screen.findByText('1. Park walk');
  expect(
    screen.queryByRole('button', { name: 'Save trip details' }),
  ).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Select this version' }),
  ).toBeNull();
  expect(screen.queryByRole('button', { name: 'Plan with Pilot' })).toBeNull();
});

it('cannot select a version after its inputs have changed', async () => {
  show(true, { ...state, versions: [{ ...version, current: false }] });
  const select = await screen.findByRole('button', {
    name: 'Select this version',
  });
  expect((select as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(select);
  expect(post).not.toHaveBeenCalled();
});

it('queues an explicit Pilot request with a retry identifier', async () => {
  show();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Plan with Pilot' }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith('/api/trips/{trip_id}/planning/runs', {
      params: { path: { trip_id: 'trip-1' } },
      body: {
        client_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
        base_id: null,
        cancelled_item_id: null,
      },
    }),
  );
});
