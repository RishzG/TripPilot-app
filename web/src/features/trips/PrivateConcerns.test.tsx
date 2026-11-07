import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type { Mock } from 'vitest';
import { api } from '@/lib/api';
import {
  CONCERNS_TILE_KEY,
  PrivateConcernsTile,
  useConcernsTileOpen,
} from './PrivateConcerns';

vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  api: { GET: vi.fn(), POST: vi.fn() },
}));
const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;

function reply(data: unknown, status = 200) {
  const ok = status < 400;
  return {
    data: ok ? data : undefined,
    error: ok ? undefined : { detail: 'x' },
    response: { ok, status },
  };
}
const own = {
  id: 7,
  client_concern_id: '550e8400-e29b-41d4-a716-446655440000',
  content: 'The boat tour is too expensive for me',
  created_at: '2026-11-06T15:00:00Z',
};
function Harness({ isOrganiser }: { isOrganiser: boolean }) {
  const [open, setOpen] = useConcernsTileOpen(false);
  return (
    <PrivateConcernsTile
      tripId="trip-1"
      isOrganiser={isOrganiser}
      open={open}
      onOpenChange={setOpen}
    />
  );
}
function show(isOrganiser = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Harness isOrganiser={isOrganiser} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  localStorage.clear();
  get.mockReset().mockResolvedValue(reply({ mine: [], anonymous: null }));
  post.mockReset();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('is honest that a small group may still guess who wrote a concern', async () => {
  show();
  expect(await screen.findByText(/may still be able to guess/)).toBeTruthy();
  expect(screen.getByText(/Other members never see your notes/)).toBeTruthy();
});

it('sends the text with a client UUID and clears the draft only after success', async () => {
  post.mockResolvedValue(reply(own, 201));
  show();
  const field = (await screen.findByLabelText(
    'Share a private concern',
  )) as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: '  Too expensive  ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send privately' }));
  await waitFor(() => expect(field.value).toBe(''));
  expect(post).toHaveBeenCalledWith('/api/trips/{trip_id}/concerns', {
    params: { path: { trip_id: 'trip-1' } },
    body: {
      content: 'Too expensive',
      client_concern_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    },
  });
});

it('keeps the draft after a failure and reuses the same client id on retry', async () => {
  post.mockResolvedValueOnce(reply({}, 500)).mockResolvedValue(reply(own, 201));
  show();
  const field = (await screen.findByLabelText(
    'Share a private concern',
  )) as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: 'Too expensive' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send privately' }));
  await screen.findByRole('alert');
  expect(field.value).toBe('Too expensive');
  fireEvent.click(screen.getByRole('button', { name: 'Send privately' }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(post.mock.calls[0]?.[1].body).toEqual(post.mock.calls[1]?.[1].body);
});

it('lists the author’s concerns with a Withdraw button that posts the withdraw route', async () => {
  get.mockResolvedValue(reply({ mine: [own], anonymous: null }));
  post.mockResolvedValue(reply({ mine: [], anonymous: null }));
  show();
  expect(await screen.findByText('Your concerns')).toBeTruthy();
  expect(screen.getByText(own.content)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /Withdraw/ }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      '/api/trips/{trip_id}/concerns/{concern_id}/withdraw',
      { params: { path: { trip_id: 'trip-1', concern_id: 7 } } },
    ),
  );
});

it('never shows the anonymous section to a member', async () => {
  show(false);
  await screen.findByText('Your concerns');
  expect(screen.queryByText('From the group (anonymous)')).toBeNull();
});

it('shows the leader the anonymous list with content and a date, and no names', async () => {
  get.mockResolvedValue(
    reply({
      mine: [],
      anonymous: [
        { content: 'Worried about the hike', submitted_on: '2026-11-05' },
      ],
    }),
  );
  show(true);
  expect(await screen.findByText('From the group (anonymous)')).toBeTruthy();
  expect(screen.getByText('Worried about the hike')).toBeTruthy();
  expect(
    screen.getByText(
      new Date('2026-11-05T00:00:00Z').toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
      }),
    ),
  ).toBeTruthy();
});

it('shows an empty state to a leader with nothing yet', async () => {
  get.mockResolvedValue(reply({ mine: [], anonymous: [] }));
  show(true);
  expect(await screen.findByText('Nothing from the group yet.')).toBeTruthy();
});

it('renders concern text as plain text', async () => {
  get.mockResolvedValue(
    reply({
      mine: [{ ...own, content: '<script>alert(1)</script>' }],
      anonymous: null,
    }),
  );
  show();
  await screen.findByText('<script>alert(1)</script>');
  expect(document.querySelector('script')).toBeNull();
});

it('is a complementary landmark with the honesty note, form and your own section', async () => {
  show();
  expect(
    screen.getByRole('complementary', { name: 'Private concerns' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('heading', { name: 'Private concerns' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('textbox', { name: 'Share a private concern' }),
  ).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Send privately' })).toBeTruthy();
  expect(
    await screen.findByRole('region', { name: 'Your concerns' }),
  ).toBeTruthy();
  expect(
    screen.queryByRole('region', { name: 'From the group (anonymous)' }),
  ).toBeNull();
});

it('splits the leader’s own concerns from the anonymous list', async () => {
  get.mockResolvedValue(
    reply({
      mine: [own],
      anonymous: [
        { content: 'Worried about the hike', submitted_on: '2026-11-05' },
      ],
    }),
  );
  show(true);
  const mine = await screen.findByRole('region', { name: 'Your concerns' });
  expect(within(mine).getByText(own.content)).toBeTruthy();
  expect(within(mine).getByText('You')).toBeTruthy();
  expect(within(mine).getByRole('button', { name: /Withdraw/ })).toBeTruthy();
  const group = screen.getByRole('region', {
    name: 'From the group (anonymous)',
  });
  expect(within(group).getByText('Worried about the hike')).toBeTruthy();
  expect(within(group).queryByText('You')).toBeNull();
  expect(within(group).queryByRole('button')).toBeNull();
  expect(within(group).queryByText(own.content)).toBeNull();
});

it('renders both lists in the order the server sends them', async () => {
  const newer = { ...own, id: 9, content: 'Newer own concern' };
  get.mockResolvedValue(
    reply({
      mine: [newer, own],
      anonymous: [
        { content: 'Newest from group', submitted_on: '2026-11-06' },
        { content: 'Oldest from group', submitted_on: '2026-11-04' },
      ],
    }),
  );
  show(true);
  const mine = await screen.findByRole('region', { name: 'Your concerns' });
  expect(
    within(mine)
      .getAllByRole('listitem')
      .map((item) => item.querySelector('p')?.textContent),
  ).toEqual(['Newer own concern', own.content]);
  const group = screen.getByRole('region', {
    name: 'From the group (anonymous)',
  });
  expect(
    within(group)
      .getAllByRole('listitem')
      .map((item) => item.querySelector('p')?.textContent),
  ).toEqual(['Newest from group', 'Oldest from group']);
});

it('collapses and expands with one toggle that keeps focus, the draft and its memory', async () => {
  show();
  const field = (await screen.findByRole('textbox', {
    name: 'Share a private concern',
  })) as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: 'Keep this draft' } });
  const collapse = screen.getByRole('button', {
    name: 'Collapse private concerns',
  });
  expect(collapse.getAttribute('aria-expanded')).toBe('true');
  collapse.focus();
  fireEvent.click(collapse);
  expect(
    screen.queryByRole('textbox', { name: 'Share a private concern' }),
  ).toBeNull();
  const expand = screen.getByRole('button', {
    name: 'Expand private concerns',
  });
  expect(expand.getAttribute('aria-expanded')).toBe('false');
  expect(document.activeElement).toBe(expand);
  expect(localStorage.getItem(CONCERNS_TILE_KEY)).toBe('collapsed');
  fireEvent.click(expand);
  const again = screen.getByRole('textbox', {
    name: 'Share a private concern',
  }) as HTMLTextAreaElement;
  expect(again.value).toBe('Keep this draft');
  expect(localStorage.getItem(CONCERNS_TILE_KEY)).toBe('open');
});

it('starts collapsed when this browser remembers a collapse', () => {
  localStorage.setItem(CONCERNS_TILE_KEY, 'collapsed');
  show();
  expect(
    screen.getByRole('button', { name: 'Expand private concerns' }),
  ).toBeTruthy();
  expect(
    screen.queryByRole('textbox', { name: 'Share a private concern' }),
  ).toBeNull();
});

describe('useConcernsTileOpen', () => {
  it('defaults to open', () => {
    const { result } = renderHook(() => useConcernsTileOpen(false));
    expect(result.current[0]).toBe(true);
  });

  it('reads a stored collapse as closed, and anything else as open', () => {
    localStorage.setItem(CONCERNS_TILE_KEY, 'collapsed');
    expect(renderHook(() => useConcernsTileOpen(false)).result.current[0]).toBe(
      false,
    );
    localStorage.setItem(CONCERNS_TILE_KEY, 'nonsense');
    expect(renderHook(() => useConcernsTileOpen(false)).result.current[0]).toBe(
      true,
    );
  });

  it('is open when forced, even if a collapse is stored', () => {
    localStorage.setItem(CONCERNS_TILE_KEY, 'collapsed');
    const { result } = renderHook(() => useConcernsTileOpen(true));
    expect(result.current[0]).toBe(true);
  });

  it('starts open and still updates when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const { result } = renderHook(() => useConcernsTileOpen(false));
    expect(result.current[0]).toBe(true);
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);
  });
});
