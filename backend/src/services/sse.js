// Server-Sent Events: scrittura lato server e lettura di uno stream (fetch) lato client.

export function sseEvent(type, data) {
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

// Legge uno stream SSE da una Response di fetch e chiama onEvent(tipo, dati) per ogni evento.
export async function readSse(body, onEvent) {
  const decoder = new TextDecoder();
  let buffer = '';
  for await (const chunk of body) {
    buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n/g, '\n');
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
      if (data.length) await onEvent(type, JSON.parse(data.join('\n')));
    }
  }
}
