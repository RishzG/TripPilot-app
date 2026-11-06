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
import type { components } from '@/lib/api-types';
import { GroupChat } from './GroupChat';

vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  api: { GET: vi.fn(), POST: vi.fn() },
}));
const get = api.GET as unknown as Mock;
const post = api.POST as unknown as Mock;
type Message = components['schemas']['MessageView'];
const sample: Message = {
  id: 10,
  account_id: 'a1',
  client_message_id: '550e8400-e29b-41d4-a716-446655440000',
  author_name: 'Maya',
  content: 'Where shall we go?',
  created_at: '2026-11-06T15:00:00Z',
};
let saved: Message[];
function reply(data: unknown, ok = true) {
  return {
    data: ok ? data : undefined,
    error: ok ? undefined : {},
    response: { ok, status: ok ? 200 : 500 },
  };
}
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <GroupChat tripId="trip-1" />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  saved = [];
  get
    .mockReset()
    .mockImplementation(async () =>
      reply({ messages: [...saved], older_cursor: null }),
    );
  post.mockReset().mockImplementation(async (_path, { body }) => {
    const message = { ...sample, ...body, id: 10 + saved.length };
    saved.push(message);
    return reply(message);
  });
});
afterEach(cleanup);

it('shows a clear empty state and prevents blank or whitespace-only sends', async () => {
  show();
  const field = await screen.findByLabelText('Message the group');
  expect(screen.getByText(/No messages yet/)).toBeTruthy();
  const button = screen.getByRole('button', {
    name: 'Send message',
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.change(field, { target: { value: ' \n ' } });
  expect(button.disabled).toBe(true);
  fireEvent.submit(field.closest('form') as HTMLFormElement);
  expect(post).not.toHaveBeenCalled();
});

it('sends multiline text with a client UUID and clears the draft only after success', async () => {
  show();
  const field = await screen.findByLabelText('Message the group');
  fireEvent.change(field, {
    target: { value: '  Let’s go hiking\nThen lunch  ' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  await screen.findByText('Let’s go hiking Then lunch');
  expect((field as HTMLTextAreaElement).value).toBe('');
  expect(post).toHaveBeenCalledWith('/api/trips/{trip_id}/messages', {
    params: { path: { trip_id: 'trip-1' } },
    body: {
      content: 'Let’s go hiking\nThen lunch',
      client_message_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    },
  });
});

it('retains a failed draft and reuses its message ID on retry', async () => {
  post.mockRejectedValueOnce(new Error('Offline'));
  show();
  const field = await screen.findByLabelText('Message the group');
  fireEvent.change(field, { target: { value: 'Museum visit?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  await screen.findByRole('alert');
  expect((field as HTMLTextAreaElement).value).toBe('Museum visit?');
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  await screen.findByText('Museum visit?');
  expect(post.mock.calls[0]?.[1].body).toEqual(post.mock.calls[1]?.[1].body);
  expect(saved).toHaveLength(1);
});

it('sends with Ctrl+Enter while plain Enter does not submit', async () => {
  show();
  const field = await screen.findByLabelText('Message the group');
  fireEvent.change(field, { target: { value: 'Keyboard message' } });
  fireEvent.keyDown(field, { key: 'Enter' });
  expect(post).not.toHaveBeenCalled();
  fireEvent.keyDown(field, { key: 'Enter', ctrlKey: true });
  await screen.findByText('Keyboard message');
  expect(post).toHaveBeenCalledTimes(1);
});

it('loads older pages in chronological order', async () => {
  get.mockImplementation(async (_path, { params }) =>
    reply(
      params.query.before
        ? {
            messages: [{ ...sample, id: 1, content: 'Earlier discussion' }],
            older_cursor: null,
          }
        : { messages: [sample], older_cursor: 10 },
    ),
  );
  show();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Load older messages' }),
  );
  await screen.findByText('Earlier discussion');
  const rows = within(
    screen.getByRole('log', { name: 'Group messages' }),
  ).getAllByRole('listitem');
  expect(rows[0]?.textContent).toContain('Earlier discussion');
  expect(rows[1]?.textContent).toContain('Where shall we go?');
  expect(
    screen.queryByRole('button', { name: 'Load older messages' }),
  ).toBeNull();
});

it('renders untrusted markup as plain text', async () => {
  saved = [{ ...sample, content: '<script>alert(1)</script>' }];
  show();
  await screen.findByText('<script>alert(1)</script>');
  expect(screen.getByRole('log').querySelector('script')).toBeNull();
});

it('retries an initial history failure without showing a writable empty conversation', async () => {
  get.mockResolvedValueOnce(reply(null, false));
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry loading' }));
  await screen.findByLabelText('Message the group');
  expect(get).toHaveBeenCalledTimes(2);
});

it('blocks repeated submits while a message is pending', async () => {
  let complete: ((value: unknown) => void) | undefined;
  post.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  show();
  const field = await screen.findByLabelText('Message the group');
  fireEvent.change(field, { target: { value: 'One message' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
  expect(
    (screen.getByRole('button', { name: 'Sending…' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect((field as HTMLTextAreaElement).disabled).toBe(true);
  complete?.(reply({ ...sample, content: 'One message' }));
  await waitFor(() => expect((field as HTMLTextAreaElement).value).toBe(''));
});
