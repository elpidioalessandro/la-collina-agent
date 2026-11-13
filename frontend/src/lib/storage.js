const KEY = 'la-collina-chat';

export function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || { sessionId: null, messages: [] };
  } catch {
    return { sessionId: null, messages: [] };
  }
}

export function save(state) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // memoria del browser non disponibile: la chat resta solo per questa pagina
  }
}
