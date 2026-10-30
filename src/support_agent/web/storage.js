// Storage can be blocked in third-party frames; keep a functional tab-local fallback.
const memory = new Map();
export const sessionState = {
  get(key) {
    try {
      return sessionStorage.getItem(key) ?? memory.get(key) ?? null;
    } catch {
      return memory.get(key) ?? null;
    }
  },
  set(key, value) {
    memory.set(key, value);
    try {
      sessionStorage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  },
  remove(key) {
    memory.delete(key);
    try {
      sessionStorage.removeItem(key);
    } catch {
      /* In-memory value was removed; browser storage is unavailable. */
    }
  },
  removePrefix(prefix) {
    for (const key of memory.keys())
      if (key.startsWith(prefix)) memory.delete(key);
    try {
      for (const key of Object.keys(sessionStorage))
        if (key.startsWith(prefix)) sessionStorage.removeItem(key);
    } catch {
      /* Existing browser storage cannot be accessed in this context. */
    }
  },
};
