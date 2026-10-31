import { fireEvent, render, screen } from '@testing-library/react';
import { EmptyState } from './EmptyState';
import { ErrorRetry } from './ErrorRetry';
import { SkeletonList } from './SkeletonList';

describe('SkeletonList', () => {
  it('shows three hidden 56px rows by default inside a busy region', () => {
    const { container } = render(<SkeletonList />);
    const region = container.firstElementChild;
    expect(region?.getAttribute('aria-busy')).toBe('true');
    const rows = container.querySelectorAll('[data-slot="skeleton"]');
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(row.getAttribute('aria-hidden')).toBe('true');
      expect(row.className).toContain('h-14');
    }
  });

  it('adds a title bar for page-level loading and honours the row count', () => {
    const { container } = render(<SkeletonList withTitle rows={2} />);
    expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(
      3,
    );
  });

  it('is a static block under reduced motion', () => {
    const { container } = render(<SkeletonList />);
    const row = container.querySelector('[data-slot="skeleton"]');
    expect(row?.className).toContain('motion-reduce:animate-none');
  });
});

describe('EmptyState', () => {
  it('renders the heading at the requested level with its description and action', () => {
    render(
      <EmptyState
        as="h3"
        title="Just you so far. Send the invite!"
        description="Copy the invite and drop it in your group chat."
        action={<button type="button">Do it</button>}
      />,
    );
    expect(
      screen.getByRole('heading', {
        level: 3,
        name: 'Just you so far. Send the invite!',
      }),
    ).toBeTruthy();
    expect(
      screen.getByText('Copy the invite and drop it in your group chat.'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Do it' })).toBeTruthy();
  });

  it('defaults to an H2 and omits what it is not given', () => {
    const { container } = render(
      <EmptyState title="No trips yet — start one!" />,
    );
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: 'No trips yet — start one!',
      }),
    ).toBeTruthy();
    expect(container.querySelector('p')).toBeNull();
  });
});

describe('ErrorRetry', () => {
  it('says what happened in plain words and retries on click', () => {
    const onRetry = vi.fn();
    render(<ErrorRetry onRetry={onRetry} />);
    expect(
      screen.getByRole('heading', { level: 1, name: "We couldn't load that." }),
    ).toBeTruthy();
    expect(
      screen.getByText('Check your connection and try again.'),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('can be an H2 inside a page that already has its H1', () => {
    render(<ErrorRetry as="h2" onRetry={() => undefined} />);
    expect(
      screen.getByRole('heading', { level: 2, name: "We couldn't load that." }),
    ).toBeTruthy();
  });
});
