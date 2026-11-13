import { randomUUID } from 'node:crypto';

const MAX_MESSAGES = 10;

export function createSessionStore({ ttlMinutes = 120, now = () => Date.now() } = {}) {
  const sessions = new Map();
  const ttl = ttlMinutes * 60 * 1000;

  function cleanup() {
    for (const [id, s] of sessions) if (now() - s.updatedAt > ttl) sessions.delete(id);
  }

  return {
    get(id) {
      cleanup();
      const valid = typeof id === 'string' && /^[0-9a-f-]{36}$/.test(id);
      if (valid && sessions.has(id)) return { id, history: sessions.get(id).history };
      const newId = valid ? id : randomUUID();
      sessions.set(newId, { history: [], updatedAt: now() });
      return { id: newId, history: sessions.get(newId).history };
    },
    append(id, ...messages) {
      const s = sessions.get(id);
      if (!s) return;
      s.history.push(...messages);
      s.history.splice(0, Math.max(0, s.history.length - MAX_MESSAGES));
      s.updatedAt = now();
    },
    reset(id) {
      return sessions.delete(id);
    },
    size: () => sessions.size,
  };
}
