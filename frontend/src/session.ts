import type { QueryClient } from "@tanstack/react-query";

export const accountQueryKey = ["account"] as const;

type SessionSnapshot = { revision: number; expired: boolean };

export function createSession() {
  let snapshot: SessionSnapshot = { revision: 0, expired: false };
  let authenticated = false;
  let controller = new AbortController();
  const listeners = new Set<() => void>();
  const endListeners = new Set<() => void>();

  function end(expired: boolean) {
    if (expired && snapshot.expired) return;
    authenticated = false;
    snapshot = { revision: snapshot.revision + 1, expired };
    const previous = controller;
    controller = new AbortController();
    previous.abort();
    endListeners.forEach((listener) => listener());
    listeners.forEach((listener) => listener());
  }

  return {
    getSnapshot: () => snapshot,
    getSignal: () => controller.signal,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    onEnd(listener: () => void) {
      endListeners.add(listener);
      return () => { endListeners.delete(listener); };
    },
    expire(allowAnonymous = false) {
      if (!allowAnonymous || authenticated) end(true);
    },
    signOut: () => end(false),
    signIn() {
      authenticated = true;
      if (snapshot.expired) {
        snapshot = { ...snapshot, expired: false };
        listeners.forEach((listener) => listener());
      }
    },
  };
}

export const session = createSession();

export function bindSessionToQueryClient(client: Pick<QueryClient, "cancelQueries" | "setQueryData">) {
  return session.onEnd(() => {
    // Cancel identity refreshes before clearing the cache so an old response
    // cannot restore an account after its session has ended.
    void client.cancelQueries({ queryKey: accountQueryKey });
    client.setQueryData(accountQueryKey, null);
  });
}
