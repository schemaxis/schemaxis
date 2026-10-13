// A minimal observable store. State is replaced, never mutated in place.

export class Store {
  constructor(initial) {
    this.state = initial;
    this.listeners = new Set();
  }

  get() {
    return this.state;
  }

  /** Merge a partial object, or apply an updater function returning one. */
  set(update) {
    const patch = typeof update === 'function' ? update(this.state) : update;
    if (!patch) {
      return;
    }
    const previous = this.state;
    this.state = {...previous, ...patch};
    for (const listener of [...this.listeners]) {
      listener(this.state, previous);
    }
  }

  /** Subscribe; returns an unsubscribe function. */
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Call listener only when selector(state) changes (shallow identity). */
  watch(selector, listener) {
    let current = selector(this.state);
    return this.subscribe((state) => {
      const next = selector(state);
      if (next !== current) {
        const previous = current;
        current = next;
        listener(next, previous);
      }
    });
  }
}

/** A tiny event bus for cross-window messages such as 'open-document'. */
export class Bus {
  constructor() {
    this.handlers = new Map();
  }

  on(name, handler) {
    if (!this.handlers.has(name)) {
      this.handlers.set(name, new Set());
    }
    this.handlers.get(name).add(handler);
    return () => this.handlers.get(name).delete(handler);
  }

  emit(name, detail) {
    for (const handler of [...(this.handlers.get(name) || [])]) {
      handler(detail);
    }
  }
}
