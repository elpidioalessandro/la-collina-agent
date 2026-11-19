// Legge la risposta in Server-Sent Events: onStep({ testo, livello }) per ogni passo, poi la risposta finale.
async function readEvents(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let end;
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let type = 'message';
      const data = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) type = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent(type, JSON.parse(data.join('\n')));
    }
  }
}

export async function sendMessage(message, sessionId, onStep = () => {}) {
  let res;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message, sessionId }),
    });
  } catch {
    throw new Error('Il server non risponde. Controlla che back end e agente dati siano accesi e riprova.');
  }
  if (!res.ok || !(res.headers.get('content-type') || '').includes('text/event-stream')) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Il server ha risposto ${res.status}`);
  }
  let answer;
  let error;
  try {
    await readEvents(res.body, (type, data) => {
      if (type === 'passo') onStep(data);
      else if (type === 'risposta') answer = data;
      else if (type === 'errore') error = data.error;
    });
  } catch {
    throw new Error('La connessione si è interrotta prima della risposta. Riprova.');
  }
  if (error) throw new Error(error);
  if (!answer) throw new Error('La connessione si è interrotta prima della risposta. Riprova.');
  return answer;
}

export function resetSession(sessionId) {
  if (!sessionId) return Promise.resolve();
  return fetch(`/api/chat/${sessionId}`, { method: 'DELETE' }).catch(() => {});
}
