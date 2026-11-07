import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

/** The event types the trip stream sends; each one means the trip view may have changed. */
export const TRIP_EVENT_TYPES = [
  'member.joined',
  'member.left',
  'member.removed',
  'trip.updated',
  'preferences.updated',
] as const;

/**
 * Keep the trip page live (D-24). Opens the trip's event stream and refetches the
 * `['trip', tripId]` query whenever something changes: on each event, when the stream
 * (re)opens, and when a backgrounded tab becomes visible again (phones resume with dead
 * sockets, so the refetch on `visibilitychange` is the backstop). The stream is
 * same-origin, so the session cookie goes with it, and the browser resends Last-Event-ID
 * on its own reconnects.
 */
export function useTripEvents(tripId: string): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (tripId === '' || typeof EventSource === 'undefined') {
      return;
    }
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ['trip', tripId] });
      void queryClient.invalidateQueries({
        queryKey: ['trip-preferences', tripId],
      });
      refreshMessages();
      refreshConcerns();
      refreshPlan();
      refreshPilot();
    };
    const refreshMessages = () => {
      void queryClient.invalidateQueries({
        queryKey: ['trip-messages', tripId],
      });
    };
    // Each viewer refetches their own projection; the events carry no private data.
    const refreshConcerns = () => {
      void queryClient.invalidateQueries({
        queryKey: ['trip-concerns', tripId],
      });
    };
    const refreshPlan = () => {
      void queryClient.invalidateQueries({
        queryKey: ['trip-plan', tripId, 'latest'],
      });
    };
    const refreshPilot = () => {
      void queryClient.invalidateQueries({ queryKey: ['trip-pilot', tripId] });
    };
    const source = new EventSource(
      `/api/trips/${encodeURIComponent(tripId)}/events`,
    );
    source.addEventListener('open', refresh);
    source.addEventListener('message.created', refreshMessages);
    source.addEventListener('concerns.changed', refreshConcerns);
    source.addEventListener('plan.version_created', refreshPlan);
    source.addEventListener('pilot.changed', refreshPilot);
    for (const type of TRIP_EVENT_TYPES) {
      source.addEventListener(type, refresh);
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refresh();
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      source.close();
    };
  }, [tripId, queryClient]);
}
