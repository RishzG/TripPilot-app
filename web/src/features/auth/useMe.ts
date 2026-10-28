import { useQuery } from '@tanstack/react-query';
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
