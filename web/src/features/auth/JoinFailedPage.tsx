import { useSearchParams } from 'react-router';
import { Notice, noticeForReason } from '../trips/joinNotices';

/**
 * Where Log in with PayPal sends someone whose invite could not be used (full, closed, removed
 * per UD-4, or a link that no longer works). They are signed in already; only the join failed.
 */
export function JoinFailedPage() {
  const [searchParams] = useSearchParams();
  return <Notice {...noticeForReason(searchParams.get('reason'))} />;
}
