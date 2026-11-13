// Storage can be blocked in third-party frames; keep a functional tab-local fallback.
const memory = new Map<string, string>();
const volatile = new Set<string>();
// Production keeps existing pending identities; static Demo never reads or clears them.
const namespace =
  typeof __DEMO__ !== "undefined" && __DEMO__ ? "kefu.static-demo." : "";
function removeKey(key: string) {
  memory.delete(key);
  volatile.delete(key);
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Keep a local tombstone if browser storage becomes readable again later.
    volatile.add(key);
  }
}
export const sessionState = {
  get(key: string) {
    key = namespace + key;
    if (volatile.has(key)) return memory.get(key) ?? null;
    try {
      return sessionStorage.getItem(key);
    } catch {
      return memory.get(key) ?? null;
    }
  },
  set(key: string, value: string) {
    key = namespace + key;
    memory.set(key, value);
    try {
      sessionStorage.setItem(key, value);
      volatile.delete(key);
      return true;
    } catch {
      volatile.add(key);
      return false;
    }
  },
  remove(key: string) {
    removeKey(namespace + key);
  },
  removePrefix(prefix: string) {
    prefix = namespace + prefix;
    const keys = new Set([...memory.keys(), ...volatile]);
    try {
      for (const key of Object.keys(sessionStorage)) keys.add(key);
    } catch {
      /* Existing browser storage cannot be accessed in this context. */
    }
    for (const key of keys) if (key.startsWith(prefix)) removeKey(key);
  },
};
