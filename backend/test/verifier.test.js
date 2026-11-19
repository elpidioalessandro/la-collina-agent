import { test } from 'node:test';
import assert from 'node:assert/strict';
import { answerNumbers, describeProblems, findProblems, isGrounded, normalizeCitations, removeProblems, sourceNumbers, tidy } from '../src/services/verifier.js';

test('le citazioni in ogni forma diventano [SEZ x.y]', () => {
  assert.equal(normalizeCitations('soglia del 70% (SEZ 8.6).'), 'soglia del 70% [SEZ 8.6].');
  assert.equal(normalizeCitations('regole (SEZ 4.4, 4.5) e 【SEZ 7.4】 【analizza_dati】'), 'regole [SEZ 4.4] [SEZ 4.5] e [SEZ 7.4]');
  assert.equal(normalizeCitations('vedi SEZ 5.3 e [SEZ 5.7, 5.8]'), 'vedi [SEZ 5.3] e [SEZ 5.7] [SEZ 5.8]');
});

test('i numeri si leggono in formato italiano e i confronti tengono conto degli arrotondamenti', () => {
  const valori = answerNumbers('Incasso 22 336,7 € e 1.098,37 €; sell-through 48,7% in AI24, anno 2024.').map((n) => n.value);
  assert.deepEqual(valori, [22336.7, 1098.37, 48.7]);
  const fonti = sourceNumbers(['{"sell_through_pct": 48.67, "euro": 1098.37}']);
  assert.ok(isGrounded({ value: 48.7, decimals: 1 }, fonti));
  assert.ok(!isGrounded({ value: 49.1, decimals: 1 }, fonti));
});

test('il controllo segnala numeri inventati, sezioni non lette e manuale non consultato', () => {
  const problemi = findProblems('Margine 32,6% contro 28,9% [SEZ 9.9]. Secondo il manuale va bene.', {
    sources: sourceNumbers(['margine_pct: 32.61']), knownCodes: new Set(), manualRead: false,
  });
  assert.deepEqual(problemi.map((p) => p.tipo), ['numeri', 'sezioni', 'manuale']);
  assert.deepEqual(problemi[0].valori, ['28,9']);
});

test('le citazioni a inizio riga non uniscono le righe e il simbolo % resta attaccato alla cifra', () => {
  assert.equal(tidy(normalizeCitations('- Sconto oltre il 10 %: 12 casi\n(SEZ 4.1) regola')), '- Sconto oltre il 10%: 12 casi\n[SEZ 4.1] regola');
});

test('frequenze inventate: segnalate se non sono nelle fonti, tolte con la loro frase', () => {
  const text = 'Proporre la taglia superiore [SEZ 2.3].\n- Monitorare i resi per taglia settimanalmente.\n- Avvisare il cliente.';
  const base = { sources: [], knownCodes: new Set(['SEZ 2.3']), manualRead: true };
  const manuale = 'i resi per taglia di questi due brand sono il primo indicatore da controllare';
  const problems = findProblems(text, { ...base, sourceText: manuale });
  assert.deepEqual(problems, [{ tipo: 'frequenze', valori: ['settimanalmente'] }]);
  assert.deepEqual(describeProblems(problems), ['frequenze che non sono né nel manuale né nei dati: settimanalmente']);
  assert.equal(removeProblems(text, problems), 'Proporre la taglia superiore [SEZ 2.3].\n- Avvisare il cliente.');
  // Se la frequenza è nel manuale (anche in un'altra forma della parola) va bene.
  assert.deepEqual(findProblems('Il riepilogo è settimanale.', { ...base, sourceText: 'il riepilogo si fa settimanalmente' }), []);
  assert.deepEqual(findProblems('La cassa si chiude ogni sera.', { ...base, sourceText: 'ogni sera si chiude la cassa' }), []);
});

test('migliaia con il punto anche quando il modello usa lo spazio', () => {
  assert.equal(tidy('Credito perso: 1 098,37 € e incasso 19 936,60 € (73 venduti su 150)'), 'Credito perso: 1.098,37 € e incasso 19.936,60 € (73 venduti su 150)');
  assert.equal(tidy('nel 2024 120 pezzi'), 'nel 2024 120 pezzi');
});

test('rinegoziazione: ammessa solo se in questo turno sono state calcolate le soglie dei fornitori', () => {
  const text = 'Lardoni: 4,7% di resi [SEZ 2.3].\n\nSe la regola non è rispettata, segnalarla al titolare per una rinegoziazione [SEZ 8.6].';
  const base = { sources: [4.7], knownCodes: new Set(['SEZ 2.3', 'SEZ 8.6']), manualRead: true };
  const problems = findProblems(text, { ...base, sourceText: 'resi: {"brand": "lardoni", "pct_sui_venduti": 4.73}' });
  assert.deepEqual(problems, [{ tipo: 'rinegoziazione', valori: [] }]);
  assert.equal(removeProblems(text, problems), 'Lardoni: 4,7% di resi [SEZ 2.3].');
  const conSoglie = 'hole in ai24: 2 soglie superate (...), va segnalato al titolare per rinegoziazione';
  assert.deepEqual(findProblems('Hole va segnalato per rinegoziazione [SEZ 8.6].', { ...base, sourceText: conSoglie }), []);
});

test('le etichette sopra/sotto copiate dai risultati spariscono', () => {
  assert.equal(tidy('tasso più alto del negozio (1° su 10 brand) [sopra].'), 'tasso più alto del negozio (1° su 10 brand).');
});
