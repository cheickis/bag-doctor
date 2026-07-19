type Listener = (event: MessageEvent) => void;

export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  onopen: ((event: Event) => void) | null = null;
  onmessage: Listener | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string | URL) { this.url = String(url); FakeEventSource.instances.push(this); }
  addEventListener(name: string, listener: EventListenerOrEventListenerObject) {
    const callback = typeof listener === "function" ? listener as Listener : listener.handleEvent.bind(listener) as Listener;
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), callback]);
  }
  close() { this.closed = true; }
  emit(name: string, data: unknown = {}) {
    const event = new MessageEvent(name, { data: JSON.stringify(data) });
    this.listeners.get(name)?.forEach(listener => listener(event));
    if (name === "message") this.onmessage?.(event);
  }
  emitError() { this.onerror?.(new Event("error")); }
  static latest() { return this.instances[this.instances.length - 1]!; }
  static reset() { this.instances = []; }
}
