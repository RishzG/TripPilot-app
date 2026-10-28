import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { api, unwrap } from '../../lib/api';

const MAX_MEMBERS = 12;

/** The trip page shell (D-24): the trip name and who is in. Invites and live updates come later. */
export function TripPage() {
  const { tripId = '' } = useParams();
  const trip = useQuery({
    queryKey: ['trip', tripId],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}', {
          params: { path: { trip_id: tripId } },
        }),
      ),
    retry: false,
  });

  if (trip.isPending) {
    return (
      <div aria-busy="true" className="mx-auto w-full max-w-md p-4 pt-6">
        <p className="text-muted-foreground">Loading your trip</p>
      </div>
    );
  }

  if (trip.isError) {
    return (
      <div className="mx-auto w-full max-w-md p-4 pt-6">
        <h1 className="text-xl font-semibold leading-[1.2]">
          We couldn't load that.
        </h1>
        <p className="mt-2 text-muted-foreground">
          Check your connection and try again.
        </p>
        <button
          type="button"
          onClick={() => trip.refetch()}
          className="mt-4 min-h-11 rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground"
        >
          Retry loading
        </button>
      </div>
    );
  }

  const { name, members } = trip.data;
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        {name}
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {members.length} of {MAX_MEMBERS} in
      </p>
      <h2 className="mt-6 text-xl font-semibold leading-[1.2]">Who's in</h2>
      <ul className="mt-4 divide-y divide-border rounded-xl border border-border">
        {members.map((member) => (
          <li
            key={member.account_id}
            className="flex min-h-14 items-center justify-between gap-2 px-4 py-2"
          >
            <span className="truncate text-base font-semibold">
              {member.display_name}
            </span>
            {member.role === 'organiser' && (
              <span className="rounded-lg border border-border bg-muted px-2 text-sm font-semibold">
                Organiser
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
