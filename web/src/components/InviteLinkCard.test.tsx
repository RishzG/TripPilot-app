import { act, fireEvent, render, screen } from '@testing-library/react';
import { toast } from 'sonner';
import {
  COPIED_ICON_MS,
  InviteLinkCard,
  type InviteLinkCardProps,
  RESET_CONFIRM_MS,
} from './InviteLinkCard';

vi.mock('sonner', () => ({ toast: vi.fn() }));

const URL_TEXT = 'https://trippilot.example/join/abc123';

function renderCard(props: Partial<InviteLinkCardProps> = {}) {
  const handlers = {
    onResetLink: vi.fn(),
    onToggleJoining: vi.fn(),
    onRetry: vi.fn(),
  };
  const view = render(
    <InviteLinkCard
      url={URL_TEXT}
      joiningClosed={false}
      {...handlers}
      {...props}
    />,
  );
  return { ...view, ...handlers };
}

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  });
}

describe('InviteLinkCard', () => {
  beforeEach(() => {
    vi.mocked(toast).mockReset();
    stubClipboard(vi.fn().mockResolvedValue(undefined));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the heading, a read-only link field and exactly one copy action', () => {
    renderCard();
    expect(
      screen.getByRole('heading', { level: 2, name: 'Invite link' }),
    ).toBeTruthy();
    const field = screen.getByLabelText(
      'Invite link address',
    ) as HTMLInputElement;
    expect(field.readOnly).toBe(true);
    expect(field.value).toBe(URL_TEXT);
    expect(
      screen
        .getAllByRole('button', { name: /copy/i })
        .map((b) => b.textContent),
    ).toEqual(['Copy invite link']);
    expect(screen.getByRole('button', { name: 'Reset link' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Close joining' })).toBeTruthy();
  });

  it('copies the link with the clipboard, toasts, swaps the icon for two seconds and swaps it back', async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    renderCard();
    const copy = screen.getByRole('button', { name: 'Copy invite link' });
    expect(copy.querySelector('.lucide-copy')).not.toBeNull();

    await act(async () => {
      fireEvent.click(copy);
    });

    expect(writeText).toHaveBeenCalledWith(URL_TEXT);
    expect(toast).toHaveBeenCalledWith(
      'Copy the invite and drop it in your group chat',
    );
    expect(copy.querySelector('.lucide-check')).not.toBeNull();
    expect(copy.textContent).toBe('Copy invite link');

    await act(async () => {
      vi.advanceTimersByTime(COPIED_ICON_MS);
    });
    expect(copy.querySelector('.lucide-copy')).not.toBeNull();
  });

  it('selects the link and says how to copy by hand when the clipboard throws', async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error('denied')));
    renderCard();
    const field = screen.getByLabelText(
      'Invite link address',
    ) as HTMLInputElement;
    const select = vi.spyOn(field, 'select');

    fireEvent.click(screen.getByRole('button', { name: 'Copy invite link' }));

    expect(
      await screen.findByText('Press and hold to copy the link.'),
    ).toBeTruthy();
    expect(select).toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it('only resets the link after the inline confirmation', () => {
    const { onResetLink } = renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Reset link' }));
    expect(onResetLink).not.toHaveBeenCalled();
    expect(
      screen.getByText('Reset? The old link stops working right away.'),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Keep old link' }));
    expect(onResetLink).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Reset link' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Reset link' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, reset' }));
    expect(onResetLink).toHaveBeenCalledTimes(1);
  });

  it('puts the Reset link button back after six seconds', () => {
    vi.useFakeTimers();
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Reset link' }));
    act(() => {
      vi.advanceTimersByTime(RESET_CONFIRM_MS);
    });
    expect(screen.getByRole('button', { name: 'Reset link' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Yes, reset' })).toBeNull();
  });

  it('closes and opens joining with one tap and shows the closed caption', () => {
    const { onToggleJoining, rerender, onResetLink } = renderCard();
    expect(screen.queryByText(/Joining is closed/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Close joining' }));
    expect(onToggleJoining).toHaveBeenCalledTimes(1);

    rerender(
      <InviteLinkCard
        url={URL_TEXT}
        joiningClosed
        onResetLink={onResetLink}
        onToggleJoining={onToggleJoining}
      />,
    );
    expect(
      screen.getByText('Joining is closed. Nobody new can use the link.'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open joining' })).toBeTruthy();
  });

  it('disables copy while the link loads and offers a retry when it fails', () => {
    const { onRetry, rerender, onResetLink, onToggleJoining } = renderCard({
      url: undefined,
    });
    const copy = screen.getByRole('button', {
      name: 'Copy invite link',
    }) as HTMLButtonElement;
    expect(copy.disabled).toBe(true);

    rerender(
      <InviteLinkCard
        url={undefined}
        joiningClosed={false}
        loadFailed
        onRetry={onRetry}
        onResetLink={onResetLink}
        onToggleJoining={onToggleJoining}
      />,
    );
    expect(screen.queryByLabelText('Invite link address')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('shows the submit-error copy when a reset or toggle failed', () => {
    renderCard({ actionFailed: true });
    expect(screen.getByRole('alert').textContent).toContain(
      "Couldn't save that. Nothing was changed, so try again.",
    );
  });

  it('fades the field only when the link is replaced, never for the first value', () => {
    const { rerender, onResetLink, onToggleJoining } = renderCard();
    const first = screen.getByLabelText('Invite link address');
    expect(first.className).not.toContain('fade-in');

    rerender(
      <InviteLinkCard
        url="https://trippilot.example/join/new456"
        joiningClosed={false}
        onResetLink={onResetLink}
        onToggleJoining={onToggleJoining}
      />,
    );
    const swapped = screen.getByLabelText(
      'Invite link address',
    ) as HTMLInputElement;
    expect(swapped.value).toBe('https://trippilot.example/join/new456');
    expect(swapped.className).toContain('motion-safe:fade-in');
  });

  it('enters with the 250ms motion-safe animation unless told it is part of first paint', () => {
    const { container, unmount } = renderCard();
    expect(container.firstElementChild?.className).toContain(
      'motion-safe:animate-in',
    );
    unmount();
    const quiet = renderCard({ animateEntrance: false });
    expect(quiet.container.firstElementChild?.className).not.toContain(
      'animate-in',
    );
  });

  it('uses theme tokens only, with no colour literal, no remote URL and no inline style', () => {
    const { container } = renderCard({ joiningClosed: true });
    const html = container.innerHTML;
    expect(html).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/);
    expect(html).not.toContain('acme.com');
    expect(container.querySelector('[style]')).toBeNull();
    expect(container.textContent).not.toContain('!');
  });
});
