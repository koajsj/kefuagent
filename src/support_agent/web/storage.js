// Storage can be blocked in third-party frames; keep a functional tab-local fallback.
const memory = new Map();
const volatile = new Set();
function removeKey(key) {
  memory.delete(key);
  volatile.delete(key);
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Prevent an acknowledged request from reappearing if storage becomes readable again.
    volatile.add(key);
  }
}
export const sessionState = {
  get(key) {
    if (volatile.has(key)) return memory.get(key) ?? null;
    try {
      return sessionStorage.getItem(key);
    } catch {
      return memory.get(key) ?? null;
    }
  },
  set(key, value) {
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
  remove(key) {
    removeKey(key);
  },
  removePrefix(prefix) {
    const keys = new Set([...memory.keys(), ...volatile]);
    try {
      for (const key of Object.keys(sessionStorage)) keys.add(key);
    } catch {
      /* Existing browser storage cannot be accessed in this context. */
    }
    for (const key of keys) if (key.startsWith(prefix)) removeKey(key);
  },
};
