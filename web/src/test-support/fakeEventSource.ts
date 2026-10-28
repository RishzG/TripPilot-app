/**
 * A stand-in for the browser's EventSource. Tests install it with
 * `vi.stubGlobal('EventSource', FakeEventSource)` and drive it with `emit`.
 */
type Listener = (event: Event) => void;

export class FakeEventSource {
  static instances: FakeEventSource[] = [];

  static reset(): void {
    FakeEventSource.instances = [];
  }

  readonly url: string;
  closed = false;
  private readonly listeners = new Map<string, Listener[]>();

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.set(
      type,
      (this.listeners.get(type) ?? []).filter((item) => item !== listener),
    );
  }

  close(): void {
    this.closed = true;
  }

  /** Deliver an event of this type to every listener, as the browser would. */
  emit(type: string, data = '{}'): void {
    const event =
      type === 'open' || type === 'error'
        ? new Event(type)
        : new MessageEvent(type, { data });
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}
