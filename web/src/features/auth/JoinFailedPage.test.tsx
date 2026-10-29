import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { JoinFailedPage } from './JoinFailedPage';

function renderFailed(reason?: string) {
  const search = reason === undefined ? '' : `?reason=${reason}`;
  const router = createMemoryRouter(
    [{ path: '/join-failed', element: <JoinFailedPage /> }],
    { initialEntries: [`/join-failed${search}`] },
  );
  render(<RouterProvider router={router} />);
}

describe('JoinFailedPage', () => {
  it.each([
    ['full', 'This trip is full', 'It already has 12 people.'],
    ['closed', 'Joining is closed', 'Ask the organiser to open it again.'],
    [
      'removed',
      "You can't join this trip",
      'The organiser removed you from this trip. Ask them to add you back.',
    ],
    [
      'not_found',
      "This invite link isn't working",
      'It may have been reset. Ask the organiser for a new one.',
    ],
  ])('reason %s reads as the locked copy', (reason, heading, body) => {
    renderFailed(reason);

    expect(
      screen.getByRole('heading', { level: 1, name: heading }),
    ).toBeTruthy();
    expect(screen.getByText(body)).toBeTruthy();
  });

  it('treats a missing or unknown reason as a bad link', () => {
    renderFailed('something-else');

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: "This invite link isn't working",
      }),
    ).toBeTruthy();
  });
});
