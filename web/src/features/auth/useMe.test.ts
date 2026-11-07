import { QueryClient } from '@tanstack/react-query';
import { forgetSignedInState, safeNextPath } from './useMe';

describe('forgetSignedInState', () => {
  it("drops the previous visitor's invite link, trips and saved-PayPal status", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['me'], { id: 'me-1' });
    queryClient.setQueryData(['invite-link', 'trip-1'], { url: 'https://x/y' });
    queryClient.setQueryData(['trips'], []);
    queryClient.setQueryData(['trip', 'trip-1'], { id: 'trip-1' });
    queryClient.setQueryData(['trip-preferences', 'trip-1'], {
      mine: { budget_cents: 12345 },
    });
    queryClient.setQueryData(['vault-status'], { saved: true });
    queryClient.setQueryData(['trip-messages', 'trip-1'], { pages: [] });
    queryClient.setQueryData(['trip-concerns', 'trip-1'], {
      mine: [{ id: 1, content: 'Private' }],
      anonymous: null,
    });

    forgetSignedInState(queryClient);

    expect(queryClient.getQueryData(['me'])).toBeUndefined();
    expect(queryClient.getQueryData(['invite-link', 'trip-1'])).toBeUndefined();
    expect(queryClient.getQueryData(['trips'])).toBeUndefined();
    expect(queryClient.getQueryData(['trip', 'trip-1'])).toBeUndefined();
    expect(
      queryClient.getQueryData(['trip-preferences', 'trip-1']),
    ).toBeUndefined();
    expect(queryClient.getQueryData(['vault-status'])).toBeUndefined();
    expect(
      queryClient.getQueryData(['trip-messages', 'trip-1']),
    ).toBeUndefined();
    expect(
      queryClient.getQueryData(['trip-concerns', 'trip-1']),
    ).toBeUndefined();
  });

  it('keeps data that is not about the visitor', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['demo-personas'], [{ slug: 'maya' }]);

    forgetSignedInState(queryClient);

    expect(queryClient.getQueryData(['demo-personas'])).toEqual([
      { slug: 'maya' },
    ]);
  });
});

describe('safeNextPath', () => {
  it('keeps a path inside the app', () => {
    expect(safeNextPath('/trips/new', '/')).toBe('/trips/new');
  });

  it.each([null, '//evil.example', 'https://evil.example', '/a\\b'])(
    'falls back for %s',
    (next) => {
      expect(safeNextPath(next, '/')).toBe('/');
    },
  );
});
