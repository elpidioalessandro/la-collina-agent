// Log strutturati del back end, nello stesso formato dell'agente dati: una riga per evento con campi
// chiave=valore, oppure JSON con LOG_FORMAT=json.
const json = (process.env.LOG_FORMAT || '').toLowerCase() === 'json';

function value(v) {
  const text = Array.isArray(v) ? v.join('+') : String(v);
  return !text || /[\s"=]/.test(text) ? `"${text.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"` : text;
}

function write(level, event, fields = {}) {
  if (process.env.NODE_ENV === 'test') return; // i test non sporcano l'output
  const now = new Date();
  if (json) {
    console.log(JSON.stringify({ ora: now.toISOString(), livello: level, evento: event, ...fields }));
    return;
  }
  const time = `${now.toLocaleDateString('sv-SE')} ${now.toLocaleTimeString('it-IT', { hour12: false })}`;
  const pairs = Object.entries(fields).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${value(v)}`);
  console.log([time, level, event, ...pairs].join(' '));
}

export const log = {
  info: (event, fields) => write('INFO', event, fields),
  warn: (event, fields) => write('WARNING', event, fields),
  error: (event, fields) => write('ERROR', event, fields),
};
