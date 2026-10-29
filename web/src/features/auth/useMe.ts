import { type QueryClient, useQuery } from '@tanstack/react-query';
import { api, unwrap } from '../../lib/api';

/**
 * The signed-in account, or null when nobody is signed in (a 401 is an answer, not an error).
 * Shared by the app shell (demo badge) and the pages that branch on signed-in or not.
 */
export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const result = await api.GET('/api/me');
      if (result.response.status === 401) {
        return null;
      }
      return unwrap(result);
    },
    retry: false,
  });
}

/**
 * Drop everything cached for the previous visitor, so nothing a signed-out or other-persona
 * session fetched is shown after sign-in (the cache is per browser, not per account).
 */
export function forgetSignedInState(queryClient: QueryClient) {
  for (const key of ['me', 'invite', 'trips', 'trip', 'vault-status']) {
    queryClient.removeQueries({ queryKey: [key] });
  }
}

/** Return `next` when it is a path inside this app, else the fallback (no open redirects). */
export function safeNextPath(next: string | null, fallback: string): string {
  if (next?.startsWith('/') && !next.startsWith('//') && !next.includes('\\')) {
    return next;
  }
  return fallback;
}
