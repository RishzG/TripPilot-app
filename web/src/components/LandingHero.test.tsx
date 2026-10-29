import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { LandingHero } from './LandingHero';

function renderHero(demoHref?: string) {
  return render(
    <MemoryRouter>
      <LandingHero
        startHref="/signin?next=%2Ftrips%2Fnew"
        demoHref={demoHref}
      />
    </MemoryRouter>,
  );
}

describe('LandingHero', () => {
  it('shows the locked headline, the body copy and Start a trip', () => {
    renderHero();
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'Plan the trip. Split it fairly.',
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'Get your group from "we should go somewhere" to booked, without anyone chasing money.',
      ),
    ).toBeTruthy();
    const start = screen.getByRole('link', { name: 'Start a trip' });
    expect(start.getAttribute('href')).toBe('/signin?next=%2Ftrips%2Fnew');
  });

  it('has exactly one H1 and no eyebrow line, image or exclamation mark', () => {
    const { container } = renderHero('/demo');
    expect(screen.getAllByRole('heading')).toHaveLength(1);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).not.toContain('!');
    expect(container.textContent).not.toContain('Production-ready');
  });

  it('offers Try the demo only when a demo link is given', () => {
    const { unmount } = renderHero();
    expect(screen.queryByRole('link', { name: 'Try the demo' })).toBeNull();
    unmount();
    renderHero('/demo');
    expect(
      screen.getByRole('link', { name: 'Try the demo' }).getAttribute('href'),
    ).toBe('/demo');
  });

  it('keeps coral for the one primary action and uses the display type token', () => {
    renderHero('/demo');
    const start = screen.getByRole('link', { name: 'Start a trip' });
    const demo = screen.getByRole('link', { name: 'Try the demo' });
    expect(start.className).toContain('bg-primary');
    expect(demo.className).not.toContain('bg-primary');
    expect(start.className).toContain('h-11');
    expect(start.className).not.toContain('rounded-full');
    expect(screen.getByRole('heading', { level: 1 }).className).toContain(
      'text-display',
    );
  });

  it('animates in once, only for people who allow motion', () => {
    const { container } = renderHero();
    const block = container.firstElementChild;
    expect(block?.className).toContain('motion-safe:animate-in');
    expect(block?.className).toContain('motion-safe:fade-in');
    expect(block?.className).not.toMatch(/(^|\s)animate-/);
  });

  it('uses theme tokens only, with no colour literal or inline style', () => {
    const { container } = renderHero('/demo');
    expect(container.innerHTML).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/);
    expect(container.querySelector('[style]')).toBeNull();
  });
});
