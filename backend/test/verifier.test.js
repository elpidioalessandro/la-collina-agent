import { test } from 'node:test';
import assert from 'node:assert/strict';
import { answerNumbers, findProblems, isGrounded, normalizeCitations, sourceNumbers, tidy } from '../src/services/verifier.js';

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
