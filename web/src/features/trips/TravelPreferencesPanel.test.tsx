import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type { Mock } from 'vitest';
import { api } from '@/lib/api';
import { budgetCents, TravelPreferencesPanel } from './TravelPreferencesPanel';

vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  api: { GET: vi.fn(), PUT: vi.fn() },
}));

const get = api.GET as unknown as Mock;
const put = api.PUT as unknown as Mock;
const mine = {
  origin: 'Chicago',
  interests: '',
  pace: 'balanced',
  budget_cents: 12345,
  dietary_notes: 'Private note',
  must_haves: 'Step-free access',
  preferred: 'Outdoor lunches',
};
const data = {
  mine,
  members: [
    {
      account_id: 'a1',
      display_name: 'Maya',
      origin: 'Chicago',
      interests: 'Museums',
      pace: 'balanced',
    },
  ],
};
function reply(value: unknown, ok = true) {
  return {
    data: ok ? value : undefined,
    error: ok ? undefined : {},
    response: { ok, status: ok ? 200 : 500 },
  };
}
function show(onSaved?: () => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TravelPreferencesPanel tripId="trip-1" onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  get.mockReset().mockResolvedValue(reply(data));
  put.mockReset().mockResolvedValue(reply(data));
});
afterEach(cleanup);

it('continues to chat only after the server accepts the saved preferences', async () => {
  const onSaved = vi.fn();
  put
    .mockResolvedValueOnce(reply(null, false))
    .mockResolvedValueOnce(reply(data));
  show(onSaved);
  fireEvent.click(
    await screen.findByRole('button', { name: 'Save preferences' }),
  );
  await screen.findByRole('alert');
  expect(onSaved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await screen.findByText('Preferences saved.');
  expect(onSaved).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Open group chat' }));
  expect(onSaved).toHaveBeenCalledTimes(2);
});

it.each([
  ['', null],
  ['0', 0],
  ['0.29', 29],
  ['400.01', 40001],
  [' 42.5 ', 4250],
  ['1000000', 100_000_000],
])('parses %s without floating-point rounding', (input, expected) => {
  expect(budgetCents(String(input))).toBe(expected);
});
it.each(['-1', '1.001', 'NaN', '1e3', '1000000.01', '1,000', 'Infinity'])(
  'rejects invalid budget %s',
  (input) => {
    expect(() => budgetCents(input)).toThrow();
  },
);

it('explains that a negative budget is not allowed', async () => {
  show();
  fireEvent.change(await screen.findByLabelText('Your trip budget (USD)'), {
    target: { value: '-1' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  expect((await screen.findByRole('alert')).textContent).toBe(
    'Budget cannot be negative.',
  );
  expect(put).not.toHaveBeenCalled();
});

it('loads private preferences only into the owner form, and sends exact cents', async () => {
  show();
  const budget = await screen.findByLabelText('Your trip budget (USD)');
  expect((budget as HTMLInputElement).value).toBe('123.45');
  expect(
    (screen.getByLabelText('Dietary notes') as HTMLTextAreaElement).value,
  ).toBe('Private note');
  const publicList = screen.getByRole('list', {
    name: 'Group preferences',
    hidden: true,
  });
  expect(within(publicList).queryByText('Private note')).toBeNull();
  expect(publicList.textContent).not.toContain('123.45');
  fireEvent.change(budget, { target: { value: '400.01' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await screen.findByText('Preferences saved.');
  expect(put).toHaveBeenCalledWith('/api/trips/{trip_id}/preferences/me', {
    params: { path: { trip_id: 'trip-1' } },
    body: { ...mine, budget_cents: 40001 },
  });
});

it('keeps a draft on save failure and retries it', async () => {
  put
    .mockResolvedValueOnce(reply(null, false))
    .mockResolvedValueOnce(reply(data));
  show();
  fireEvent.change(await screen.findByLabelText('Starting city'), {
    target: { value: 'Boston' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await screen.findByRole('alert');
  expect(
    (screen.getByLabelText('Starting city') as HTMLInputElement).value,
  ).toBe('Boston');
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await screen.findByText('Preferences saved.');
  expect(put).toHaveBeenCalledTimes(2);
});

it('updates every saved shared field from the save response without a follow-up GET', async () => {
  const saved = {
    mine: {
      ...mine,
      origin: 'Boston',
      interests: 'Walking and museums',
      pace: 'active',
    },
    members: [
      {
        ...data.members[0],
        origin: 'Boston',
        interests: 'Walking and museums',
        pace: 'active',
      },
    ],
  };
  put.mockResolvedValueOnce(reply(saved));
  const client = show();
  const origin = await screen.findByLabelText('Starting city');
  fireEvent.change(origin, { target: { value: '  Boston  ' } });
  fireEvent.change(screen.getByLabelText('Interests'), {
    target: { value: 'Walking and museums' },
  });
  fireEvent.change(screen.getByLabelText('Travel pace'), {
    target: { value: 'active' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await screen.findByText('Preferences saved.');
  const list = screen.getByRole('list', {
    name: 'Group preferences',
    hidden: true,
  });
  expect(list.textContent).toContain('Boston');
  expect(list.textContent).toContain('Walking and museums');
  expect(list.textContent).toContain('Active pace');
  expect((origin as HTMLInputElement).value).toBe('Boston');
  expect(client.getQueryData(['trip-preferences', 'trip-1'])).toEqual(saved);
  expect(get).toHaveBeenCalledTimes(1);
});

it('prevents invalid budgets from reaching the API and permits clearing', async () => {
  show();
  const budget = await screen.findByLabelText('Your trip budget (USD)');
  fireEvent.change(budget, { target: { value: '4.001' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await screen.findByRole('alert');
  expect(put).not.toHaveBeenCalled();
  fireEvent.change(budget, { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }));
  await waitFor(() => expect(put).toHaveBeenCalled());
  expect(put.mock.calls[0]?.[1].body.budget_cents).toBeNull();
});

it('retries loading without replacing a failed request with an empty editable form', async () => {
  get
    .mockResolvedValueOnce(reply(null, false))
    .mockResolvedValueOnce(reply(data));
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry loading' }));
  await screen.findByLabelText('Starting city');
  expect(get).toHaveBeenCalledTimes(2);
});
