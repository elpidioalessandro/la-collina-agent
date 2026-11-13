export async function sendMessage(message, sessionId) {
  let res;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, sessionId }),
    });
  } catch {
    throw new Error('Il server non risponde. Controlla che back end e agente dati siano accesi e riprova.');
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.error) throw new Error(body.error || `Il server ha risposto ${res.status}`);
  return body;
}

export function resetSession(sessionId) {
  if (!sessionId) return Promise.resolve();
  return fetch(`/api/chat/${sessionId}`, { method: 'DELETE' }).catch(() => {});
}
