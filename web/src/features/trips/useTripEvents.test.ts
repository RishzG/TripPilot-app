import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { FakeEventSource } from '../../test-support/fakeEventSource';
import { useTripEvents } from './useTripEvents';

function setup(tripId = 'trip-1') {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  const view = renderHook(({ id }) => useTripEvents(id), {
    wrapper,
    initialProps: { id: tripId },
  });
  return { invalidate, ...view };
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event('visibilitychange'));
}

function onlySource(): FakeEventSource {
  const source = FakeEventSource.instances[0];
  if (source === undefined) {
    throw new Error('no EventSource was opened');
  }
  return source;
}

describe('useTripEvents', () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal('EventSource', FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setVisibility('visible');
  });

  it("opens the trip's event stream on the same origin", () => {
    setup('trip-1');
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(onlySource().url).toBe('/api/trips/trip-1/events');
  });

  it.each(['member.joined', 'member.left', 'member.removed', 'trip.updated'])(
    'invalidates the trip query on %s',
    (type) => {
      const { invalidate } = setup('trip-1');
      onlySource().emit(type, '{"account_id":"a2"}');
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['trip', 'trip-1'] });
    },
  );

  it('refetches when the stream (re)opens, so nothing between load and connect is missed', () => {
    const { invalidate } = setup('trip-1');
    onlySource().emit('open');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['trip', 'trip-1'] });
  });

  it('invalidates when the tab becomes visible again, not when it hides', () => {
    const { invalidate } = setup('trip-1');
    setVisibility('hidden');
    expect(invalidate).not.toHaveBeenCalled();
    setVisibility('visible');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['trip', 'trip-1'] });
  });

  it('closes the stream and stops listening on unmount', () => {
    const { invalidate, unmount } = setup('trip-1');
    unmount();
    expect(onlySource().closed).toBe(true);
    setVisibility('visible');
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('moves to the new trip when the trip id changes', () => {
    const { rerender } = setup('trip-1');
    rerender({ id: 'trip-2' });
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[0]?.closed).toBe(true);
    expect(FakeEventSource.instances[1]?.url).toBe('/api/trips/trip-2/events');
  });

  it('does nothing where EventSource does not exist', () => {
    vi.unstubAllGlobals();
    expect(() => setup('trip-1')).not.toThrow();
  });
});
