# La Collina: un agente AI a supporto delle decisioni del punto vendita

[![Test](https://github.com/elpidioalessandro/la-collina-agent/actions/workflows/test.yml/badge.svg)](https://github.com/elpidioalessandro/la-collina-agent/actions/workflows/test.yml)

Agente AI ibrido per un negozio multimarca di abbigliamento uomo. Commessi e titolare fanno domande in chat: l'LLM decide da solo se cercare la risposta nel **manuale del negozio** (RAG su ChromaDB) o affidarla a un **agente dati Python** che analizza vendite e ordini con pandas e disegna grafici. Per le domande che chiedono numeri e regole insieme usa entrambi.

Ogni risposta riporta le **sezioni del manuale** usate, una **nota sulla qualità dei dati** (righe usate, scartate e corrette) e gli **strumenti chiamati**. Mentre lavora, la chat mostra in diretta cosa sta facendo: «Cerco nel manuale…», «Analizzo i resi (Lardoni)…», «Controllo numeri e fonti…».

```bash
cp .env.example .env    # inserisci la GROQ_API_KEY
./start.sh              # installa ciò che manca e avvia tutto su http://localhost:5173
```

> Negozio, brand, fornitori e dati sono di fantasia; eventuali omonimie sono casuali. Il progetto è ispirato a un negozio reale in cui ho lavorato come commesso.

---

## Architettura

```
 Browser (React)             Back end (Node + Express)                  Agente dati (Python + FastAPI)
┌──────────────────┐ POST  ┌────────────────────────────────┐  /cerca   ┌──────────────────────────────┐
│ chat + memoria   │──────▶│ /api/chat                      │──────────▶│ RAG: ChromaDB + BM25         │──▶ la_collina_kb.txt
│ passi in diretta │       │ sessione (ultimi 10 messaggi)  │           │                              │
│ grafici, fonti   │◀──────│ orchestratore ReAct            │ /analizza │ pulizia → agente pandas      │──▶ vendite.csv
│ "come ho         │  SSE  │ function calling:              │ /stream   │ (LangChain, 12 strumenti)    │──▶ ordini.csv
│  risposto"       │       │ cerca_manuale · analizza_dati  │◀── SSE ───│ grafici PNG su disco         │
└──────────────────┘       └────────────────────────────────┘           └──────────────────────────────┘
     Vite :5173                     :3001   │                                      :8000   │
                                            └──── Groq (gpt-oss-120b · gpt-oss-20b) ───────┘
```

| Livello | Tecnologia |
|---|---|
| Front end | React 19, Vite, react-markdown |
| Back end | Node.js, Express 5, SDK `openai` (function calling nativo) |
| Agente dati | Python 3.12, FastAPI, pandas, LangChain (`create_agent`), matplotlib, seaborn |
| RAG | ChromaDB locale (embedding multilingue ONNX `paraphrase-multilingual-MiniLM-L12-v2`) + BM25 |
| LLM | Groq, API compatibile OpenAI: `openai/gpt-oss-120b` per l'orchestratore, `openai/gpt-oss-20b` per l'agente dati |

**Perché due modelli e non uno.** L'orchestratore Node vede la conversazione e sceglie gli strumenti; l'agente dati Python vede solo una domanda alla volta, già riscritta in forma completa dall'orchestratore ("e Cruciverba?" diventa "Resi di Cruciverba per motivo, confrontati con gli altri brand"). Così la memoria vive in un posto solo e il servizio Python resta senza stato, facile da testare.

I due agenti usano due modelli diversi perché sul piano gratuito di Groq il limite di token al minuto (8.000) vale per modello: con un modello solo, una domanda ibrida lo superava e le risposte arrivavano oltre i 90 secondi. L'agente dati sceglie gli strumenti e passa i numeri, che arrivano già calcolati: basta il modello più piccolo. Il testo finale lo scrive l'orchestratore, sul modello più grande.

---

## API

### Back end (`:3001`)
| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/chat` | `{ "message": "...", "sessionId": "..." }`; senza `sessionId` ne crea uno. Con `Accept: text/event-stream` risponde in SSE (vedi sotto), altrimenti con un JSON unico |
| `DELETE` | `/api/chat/:sessionId` | Cancella la memoria della conversazione |
| `GET` | `/api/grafici/:nome` | Proxy verso il grafico PNG creato dall'agente dati |
| `GET` | `/api/health` | Stato del back end e dell'agente dati |

In streaming arrivano eventi `passo` mentre l'assistente lavora, poi `risposta` con il JSON completo (o `errore`). Ogni 10 secondi senza eventi arriva un commento SSE, così Safari non chiude la connessione:

```
event: passo
data: {"testo":"Chiedo all'agente dati: «Resi di Lardoni per motivo»"}

event: passo
data: {"testo":"Analizzo i resi (Lardoni)","livello":2}

event: risposta
data: {"sessionId":"…","risposta":"…","grafici":[…],"fonti":[…],"strumenti":[…],"controllo":{…},"nota_dati":"…"}
```

Il JSON della risposta:

```json
{
  "sessionId": "cfd6d235-6ab7-4135-9dd2-0150ef7dd7d3",
  "risposta": "Lardoni registra il 3,29% di resi per taglia, il valore più alto tra tutti i brand ...",
  "grafici": [{ "nome": "a7c8f7f58caa.png", "url": "/api/grafici/a7c8f7f58caa.png" }],
  "fonti": [{ "codice": "SEZ 2.2", "titolo": "Guida alla vestibilità per brand" }],
  "strumenti": [
    { "strumento": "analizza_dati", "domanda": "Resi di Lardoni per motivo, confrontati con gli altri brand", "esito": "resi" },
    { "strumento": "cerca_manuale", "domanda": "Vestibilità di Lardoni e come evitare i resi per taglia", "esito": "SEZ 2.3, SEZ 2.2, SEZ 5.3, SEZ 10.4" }
  ],
  "controllo": { "esito": "superato", "problemi": [] },
  "nota_dati": "Dati: 16569 righe di vendite e 4514 di ordini; 167 righe duplicate scartate, 1983 valori corretti in pulizia."
}
```

### Agente dati (`:8000`)
| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/cerca` | `{ "domanda": "...", "k": 4 }` → sezioni del manuale con codice, titolo e testo |
| `POST` | `/sezioni` | `{ "codici": ["SEZ 8.6"] }` → testo delle sezioni, per il controllo finale delle citazioni |
| `POST` | `/analizza` | `{ "domanda": "..." }` → risposta, grafici, passaggi, risultati degli strumenti, nota sui dati |
| `POST` | `/analizza/stream` | Come `/analizza`, in SSE: un evento `passo` per ogni strumento scelto, poi `risultato` |
| `POST` | `/ricarica` | Rilegge e ripulisce i CSV senza riavviare (vedi *Aggiornare i dati*) |
| `GET` | `/resoconto-pulizia` | Tutte le correzioni fatte ai dati |
| `GET` | `/grafici/:nome` | File PNG |
| `GET` | `/salute` | Righe caricate, sezioni del manuale, ora del caricamento e se i CSV sono cambiati da allora |

---

## Dati

| File | Contenuto |
|---|---|
| `data/vendite.csv` | 16.569 movimenti di cassa (vendite, resi, buoni regalo), marzo 2023 – febbraio 2026, 20 colonne |
| `data/ordini.csv` | 4.514 righe d'ordine ai fornitori, 16 colonne |
| `data/la_collina_kb.txt` | Manuale del negozio: 54 sezioni in 10 parti (resi e buoni, garanzia legale, sconti e saldi, taglie, cassa, regolamento del personale, fornitori, fine stagione, controlli) |
| `valutazione/` | Dati veri prima degli errori e registro delle anomalie: servono solo a verificare la pulizia e le risposte. **L'agente non li legge mai** |
| `notebooks/` | Generatore del dataset, esplorazione, pulizia e risposte attese |

Il dataset è **generato** (`notebooks/catalogo → ordini → calendario → vendite → anomalie`, seed fisso), ma con una logica da negozio vero: saldi a scaglioni con le date della Regione Marche, picchi di dicembre, meteo diverso per stagione, resi con motivo, buoni con scadenza, riassortimenti, e un titolare che corregge gli ordini in base al sell-through dell'anno prima.

Ogni brand ha **un problema piantato**, da far scoprire all'agente: Lardoni e Cruciverba vestono piccolo (resi per taglia), Dipartimento 3 ha più difetti, FreePlace e Lido Club vendono poco, Hole consegna incompleto.

Sopra ci sono due famiglie di anomalie:

| Tipo | Esempi | Cosa ne fa il sistema |
|---|---|---|
| **Errori di registrazione** (il fatto è giusto, è scritto male) | 164 righe duplicate, date in due formati, prezzi con la virgola o negativi, taglie e brand scritti in 10 modi, sconti che non tornano con il prezzo, codici articolo inesistenti | **Corretti** dalla pulizia, e dichiarati |
| **Violazioni delle regole** (il fatto è scritto bene, ma non doveva succedere) | 12 sconti oltre il tetto del 10%, 15 saldi nel periodo vietato, 5 profumi in saldo, 6 vendite il lunedì mattina a negozio chiuso | **Segnalati**, con la sezione del manuale violata |

Regola: nel dubbio, si segnala e non si corregge.

### Aggiornare i dati
I CSV si leggono e si puliscono **una volta, all'avvio** (`api.py` → `analisi.Dati.da_csv`), non a ogni domanda: la pulizia di 16.000 righe richiede meno di un secondo, ma ripeterla a ogni richiesta non avrebbe senso. Quando i file cambiano:

1. si sostituiscono `data/vendite.csv` e `data/ordini.csv` (stesse colonne);
2. `GET /salute` risponde `"file_cambiati": true`;
3. `curl -X POST http://127.0.0.1:8000/ricarica` rilegge e ripulisce i file senza riavviare. Le domande già in corso finiscono con i dati vecchi, le nuove usano quelli nuovi. In alternativa basta riavviare il servizio.

Se i file nuovi sono malformati, `/ricarica` risponde 422 e **restano i dati di prima**. `data_agent/caricamento.py` controlla la struttura prima della pulizia e dice quale file e cosa correggere: file mancante o vuoto, solo intestazione, separatore `;`, colonne mancanti, righe con campi in più, valori non numerici in prezzi e quantità (con il numero di riga), codifica diversa da UTF-8. Le righe con una data illeggibile vengono scartate e dichiarate nel resoconto della pulizia.

---

## Scelte tecniche

### 1. Pulizia deterministica prima dell'LLM
I dati non arrivano mai sporchi al modello. `data_agent/pulizia.py` applica una ventina di regole in un ordine preciso (prima i duplicati, poi date, prezzi, sconti ricalcolati dal prezzo pagato, prezzi mancanti ricostruiti da listino e sconto, motivi dedotti da sconto e data) e restituisce un **resoconto** con le righe toccate da ogni regola. Le stesse regole sono scritte in italiano nella Parte 10 del manuale, così l'agente può spiegare *perché* ha corretto un dato.

Verifica sul riferimento (`notebooks/pulizia.ipynb`): su 16.405 × 19 celle di vendite e 4.511 × 15 di ordini **resta una sola cella diversa**, un codice articolo con due candidati possibili che la pulizia sceglie di non indovinare.

### 2. I numeri vengono solo dagli strumenti
L'agente dati non calcola a mente: ha 12 strumenti (`incasso`, `sell_through`, `confronta_stagioni`, `soglie_fornitori`, `resi`, `margine`, `sconti`, `controlli_regole`, `resoconto_pulizia`, `crea_grafico`, `info_dati`, `esegui_codice_pandas`). Il codice pandas libero è l'ultima risorsa, con un massimo di 3 tentativi e l'errore restituito al modello perché si corregga.

All'orchestratore arrivano sia la risposta dell'agente dati sia i **risultati grezzi degli strumenti**, con una regola esplicita: si possono usare solo quei numeri. È la correzione a un errore trovato nei test: quando l'agente dati creava solo il grafico senza leggere i valori, l'orchestratore "riempiva" la risposta con numeri plausibili e inventati.

Se la domanda chiede un grafico e il modello si limita al calcolo, il grafico lo disegna il codice con la stessa metrica e gli stessi filtri dell'ultimo strumento usato. I resi di un brand arrivano con la sua posizione tra gli altri (*«4° su 10 per tasso di resi»*), perché «sotto il negozio» non diventi «il più basso». E `sell_through` restituisce anche `da_segnalare_per_rinegoziare`, calcolato con le quattro soglie della SEZ 8.6: nei test il modello trasformava «sotto il 70%» in «da segnalare», che per il manuale non basta.

Anche i confronti arrivano già calcolati: `resi`, `sell_through` e `margine` restituiscono il dato complessivo del negozio e, riga per riga, se il valore è sopra o sotto; `confronta_stagioni` restituisce una stagione contro la stessa stagione dell'anno prima e dopo, con le differenze. Il modello copia il confronto invece di farlo a mente, perché nei test scriveva "inferiore" accanto a un numero più grande.

**Controllo finale della risposta** (`backend/src/services/verifier.js`). Prima dell'invio il codice, non il modello, verifica cinque cose:

| Verifica | Se fallisce |
|---|---|
| Ogni numero della risposta compare nei risultati degli strumenti, nel manuale letto o nella domanda **di questo turno** (con tolleranza sugli arrotondamenti). I numeri dei messaggi precedenti non fanno fede: parlano di un altro brand o di un altro periodo | la risposta torna al modello con l'elenco dei numeri non trovati |
| Ogni sezione citata, in qualsiasi forma (`[SEZ 8.6]`, `(SEZ 8.6)`, `【SEZ 8.6】`), è stata letta | se la sezione esiste viene letta e il modello ricontrolla cosa le attribuisce; se non esiste, la citazione sparisce |
| Il manuale si nomina solo se è stato consultato | la risposta torna al modello |
| Una rinegoziazione con un fornitore si propone solo se in questo turno sono state calcolate le soglie della SEZ 8.6 | la risposta torna al modello; se ci riprova, la frase sparisce. Nei test il modello scriveva che Lardoni «supera la soglia dell'1%», confondendo i resi totali con quelli per difetto |
| Frequenze e scadenze a parole («settimanalmente», «ogni mese») compaiono nel manuale letto o nei dati | la risposta torna al modello; se ci riprova, la frase sparisce. Nei test il modello aggiungeva alle azioni un «monitorare settimanalmente» che il manuale non dice |

Prima ancora del controllo finale c'è un controllo sulle domande di seguito: se la risposta contiene numeri e in questo turno l'agente dati non è stato chiamato, il modello deve chiamarlo prima di rispondere. Nei test, a *«E Cruciverba?»* rispondeva con i numeri di Lardoni presi dalla conversazione.

Il modello ha una sola seconda possibilità: se sbaglia ancora, le frasi con numeri, frequenze, rinegoziazioni o fonti non verificati vengono tolte. L'esito del controllo compare in *Come ho risposto* e nel log del back end.

### 3. RAG ibrido: significato + parole, e quanto pesa davvero
La ricerca fonde due classifiche con **Reciprocal Rank Fusion**: un indice **BM25** sulle sezioni (parole ridotte alle prime 5 lettere, così *profumo* e *profumi* coincidono) e la ricerca per significato di **ChromaDB**. L'embedding è `paraphrase-multilingual-MiniLM-L12-v2` in ONNX quantizzato (`data_agent/embedding.py`), eseguito con onnxruntime e tokenizers che arrivano già con chromadb: nessuna dipendenza in più, niente PyTorch.

Prima l'embedding era quello predefinito di ChromaDB, `all-MiniLM-L6-v2`, addestrato sull'inglese. La scelta è stata misurata, non assunta: `python data_agent/valuta_rag.py` confronta le configurazioni su 41 domande (`valutazione/domande_rag.csv`). Venti domande usano le parole del manuale, ventuno usano sinonimi che nel manuale non ci sono: *acqua di colonia* per profumo, *svendita* per saldi, *ditta* per fornitore, *vacanza* per ferie. Una risposta è giusta se una delle sezioni attese è tra le prime *k*; `--k` sceglie quante.

| Configurazione | Prime 4: parole (20) | Prime 4: sinonimi (21) | Prime 4: tutte (41) | Prime 6: tutte (41) | Al primo posto | MRR |
|---|---|---|---|---|---|---|
| solo parole (BM25) | **20** | 11 | 31 | 33 | **25** | **0,69** |
| solo embedding inglese | 18 | 7 | 25 | 28 | 14 | 0,48 |
| solo embedding multilingue | 17 | 12 | 29 | 30 | 18 | 0,57 |
| BM25 + embedding inglese (prima) | **20** | 10 | 30 | 33 | 23 | 0,66 |
| **BM25 + embedding multilingue (ora)** | 19 | **13** | **32** | **35** | 21 | 0,66 |

Cosa dicono questi numeri:
- **L'embedding inglese non aggiungeva niente.** La fusione con BM25 faceva peggio di BM25 da solo (30 contro 31 tra le prime 4): l'ibrido di prima non era giustificato.
- **Quello multilingue serve dove BM25 non arriva: i sinonimi.** Lì la fusione trova 13 sezioni su 21 contro le 11 di BM25 (15 contro 13 tra le prime 6). Al primo posto, però, BM25 da solo resta più preciso.
- **Il guadagno è piccolo.** Si passa da 31 a 32 su 41 tra le prime 4, e da 33 a 35 tra le prime 6. Su 41 domande, una o due risposte di differenza non bastano per dire che una configurazione sia migliore. Oggi la parte semantica pesa poco: la tengo perché è l'unica che recupera i sinonimi senza un dizionario scritto a mano.
- **Per questo l'orchestratore legge 6 sezioni e non 4.** Il motivo è un caso vero della demo: con la domanda *«regole per i resi per taglia e procedure di cambio in negozio»* la sezione giusta, la 2.3, arrivava quinta e restava fuori. Sei sezioni costano circa 300 token in più a domanda, che sul piano gratuito sono sostenibili. Nel prompt l'orchestratore ha anche l'istruzione di cercare con le parole del manuale (*«Come evitare i resi per taglia»*).
- **Restano 6 domande con sinonimi su 21 che la fusione non trova tra le prime 6** (*«tagliando della cassa»*, *«scatolone… bolla»*). In pratica il caso è meno grave: l'orchestratore riscrive la domanda prima di cercare, spesso con le parole del manuale. Quel passaggio però dipende dal modello e non è misurato qui, perché la valutazione non chiama Groq.

Non ho cercato i pesi della fusione o le stopword migliori su queste stesse 41 domande: sarebbe come scegliere la configurazione guardando le risposte del test. Per farlo servirebbe un secondo insieme di domande, tenuto da parte.

Il manuale è diviso per sezione `[SEZ x.y]`, non a blocchi di lunghezza fissa: ogni pezzo è una regola completa e citabile. L'indice si ricostruisce da solo quando il file cambia (impronta MD5 nel nome della collezione).

### 4. Correlazione non è causa
Il prompt di entrambi gli agenti distingue cosa dicono i dati da perché: *"il calo dei cappotti nell'inverno 2024 si vede; il meteo non è nei dati, quindi è un'ipotesi da verificare"*. Le spiegazioni che non vengono dai dati o dal manuale vanno dichiarate come ipotesi.

### 5. Resilienza con il free tier di Groq
| Problema | Comportamento |
|---|---|
| 429 (limite di richieste) | attesa e nuovo tentativo; se persiste, messaggio chiaro all'utente |
| 400 (il modello chiama uno strumento inesistente) | nuovo tentativo con l'indicazione degli strumenti validi |
| Risposta vuota (ragionamento che esaurisce i token) | nuovo tentativo, poi risposta forzata senza strumenti |
| Troppi passaggi ReAct | dopo 5 passaggi, risposta con quello che è stato raccolto |
| Agente dati spento | l'errore arriva al modello, che lo comunica invece di bloccarsi |
| Risposta oltre i 60 s (Safari chiude le richieste inattive) | la risposta arriva in SSE: passi intermedi e, nelle pause, un commento ogni 10 s |

### 6. Più domande insieme
Lo stato di una domanda (dati, grafici creati, tentativi di codice pandas) vive in una `ContextVar` (`strumenti.StatoDomanda`), non in una variabile globale: due domande che arrivano insieme non si vedono a vicenda. I grafici degli strumenti si disegnano su una `Figure` creata a parte, senza toccare lo stato globale di pyplot; solo il codice pandas libero, che può usare `plt`, passa da un lock. Due test fanno girare due domande in parallelo e controllano che grafici e tentativi restino separati.

### 7. Log
Entrambi i servizi scrivono una riga per evento con campi `chiave=valore`, o JSON con `LOG_FORMAT=json`:

```
2026-11-19 15:27:19 INFO analizza id=97e42b4c durata_s=5.2 strumenti=resi+crea_grafico grafici=1 errori=0 domanda="Resi di Lardoni per motivo"
2026-11-19 15:27:21 INFO chat durata_s=8.4 strumenti=analizza_dati controllo=superato sessione=09c22f7d domanda="Lardoni ha troppi resi?"
```

Nell'agente dati ogni richiesta ha un `id`, che compare anche negli avvisi (limite di Groq, risposta vuota, errori), così le righe di una domanda si ritrovano anche con più richieste insieme. `LOG_LEVEL=DEBUG` aggiunge una riga per ogni strumento scelto dal modello.

### 8. Grafici su disco
I PNG si salvano in `data_agent/grafici/` e vengono cancellati dopo `GRAFICI_MAX_ORE` (24 di default): all'avvio e, al massimo ogni 10 minuti, quando se ne crea uno nuovo. Se una conversazione vecchia rimanda a un grafico cancellato, la chat lo dice invece di mostrare un'immagine rotta.

### 9. Sicurezza
| Rischio | Contromisura |
|---|---|
| Chiave API esposta | solo nel file `.env`, escluso da git; nel repo c'è solo `.env.example` |
| Quota esaurita da uno script | rate limit: 10 domande al minuto per IP, 300 al giorno in totale |
| Path traversal sui grafici | Node accetta solo nomi nel formato `[0-9a-f]{12}.png`; Python serve solo file `.png` della cartella dei grafici |
| Domande enormi | massimo 1.000 caratteri, corpo JSON massimo 20 kB |
| Dati personali | nessun dato su clienti identificati o singoli dipendenti; l'agente lo dichiara se glieli chiedono |

### 10. Test
Nessun test chiama Groq: l'LLM è sostituito da modelli finti che seguono un copione. A ogni push li esegue [GitHub Actions](.github/workflows/test.yml), insieme alla build del front end.

| Suite | Test | Cosa verifica |
|---|---|---|
| `data_agent/tests` (pytest) | 57 | pulizia uguale al riferimento, risposte attese (sell-through con i brand da segnalare davvero, resi per motivo con il totale e la posizione del brand, controlli, confronto tra stagioni, confronti con il negozio, soglie del sell-through spiegate come nel manuale, brand da segnalare secondo la SEZ 8.6), CSV malformati (file vuoto, solo intestazione, separatore `;`, colonne mancanti, campi in più, valori non numerici, codifica, date illeggibili), errori leggibili, limite di tentativi del codice, grafici salvati e cancellati dopo la scadenza, due domande in parallelo, RAG su 12 domande e validità del set di valutazione, agente e API con LLM finto, grafico creato dal codice se il modello lo dimentica, streaming, ricarica dei dati, formato dei log |
| `backend/test` (node:test) | 32 | orchestratore: scelta degli strumenti, domande ibride, memoria, retry su 400 e 429, limite di passaggi, agente dati spento; controllo finale: numeri inventati, sezioni non lette, manuale non consultato, citazioni in ogni forma senza unire le righe, numeri scritti dall'agente dati non accettati come fonte, frequenze inventate, numeri presi dalla conversazione precedente, rinegoziazione senza il calcolo delle soglie; streaming: passi nell'ordine, eventi spezzati, errori come evento; HTTP: validazione, sessione, proxy dei grafici, SSE |

---

## Avvio in locale

Prerequisiti: Python ≥ 3.12, Node.js ≥ 20, `curl`, una API key gratuita di [Groq](https://console.groq.com/keys).

```bash
git clone https://github.com/elpidioalessandro/la-collina-agent.git && cd la-collina-agent
cp .env.example .env    # inserisci la GROQ_API_KEY: è l'unico file da compilare
./start.sh              # oppure: make dev
```

`start.sh` crea l'ambiente Python in `data_agent/.venv`, installa le dipendenze Python e Node (solo se mancano o sono cambiate), controlla che la chiave ci sia e che le porte siano libere, poi avvia i tre servizi nello stesso terminale, con i log preceduti da `[dati]`, `[backend]` e `[web]`. Quando tutto risponde scrive *Apri http://localhost:5173*. `Ctrl+C` ferma tutto.

Al primo avvio l'agente dati scarica il modello di embedding multilingue (circa 135 MB) in `~/.cache/chroma/onnx_models/multilingue`.

```bash
./start.sh test         # oppure: make test · test Python e Node e build del front end, senza chiamare Groq
```

<details>
<summary>Avvio manuale, un servizio per terminale</summary>

```bash
# 1. agente dati
cd data_agent && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python api.py         # http://127.0.0.1:8000

# 2. back end
cd backend && npm ci && npm start                         # http://localhost:3001

# 3. front end
cd frontend && npm ci && npm run dev                      # http://localhost:5173
```
Tutti e tre leggono lo stesso `.env` della cartella principale.
</details>

### Variabili d'ambiente
Un solo file, `.env` nella cartella principale, letto da agente dati, back end e front end (il front end solo per la porta del back end):

| Variabile | Default | A cosa serve |
|---|---|---|
| `GROQ_API_KEY` | — | chiave di Groq, obbligatoria |
| `ORCHESTRATOR_MODEL` | `openai/gpt-oss-120b` | modello dell'orchestratore (back end) |
| `DATA_AGENT_MODEL` | `openai/gpt-oss-20b` | modello dell'agente dati |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | qualsiasi API compatibile OpenAI |
| `LLM_REASONING_EFFORT` | `low` | ragionamento dei modelli gpt-oss |
| `DATA_AGENT_PORT` · `BACKEND_PORT` | `8000` · `3001` | porte dei servizi |
| `CORS_ORIGIN` | `http://localhost:5173` | origine ammessa dal back end |
| `LOG_FORMAT` · `LOG_LEVEL` | `testo` · `INFO` | formato (`testo` o `json`) e livello dei log |
| `GRAFICI_MAX_ORE` | `24` | dopo quante ore si cancellano i PNG |

Chi aveva già `data_agent/.env` e `backend/.env` delle versioni precedenti può tenerli: vengono ancora letti, ma se una variabile è anche nel `.env` principale vince quello.

### Domande per provarlo
| Tipo | Domanda |
|---|---|
| Manuale | Una cliente vuole cambiare un capo preso in saldo: si può? |
| Dati + grafico | Mostrami il sell-through per brand con un grafico |
| Ibrida | Perché Lardoni ha così tanti resi e cosa possiamo fare? |
| Memoria | (subito dopo) E Cruciverba? |
| Controlli | Quali regole del negozio sono state violate nei dati? |
| Onestà | Perché nel 2024 i cappotti sono andati male? |

---

## Struttura

```
├── frontend/                  React + Vite
│   └── src/
│       ├── components/        Message, Suggestions, TypingIndicator
│       └── lib/               api (lettura SSE), storage
├── backend/                   Node + Express
│   ├── src/
│   │   ├── config/            env
│   │   ├── middleware/        rateLimit, errorHandler
│   │   ├── prompts/           systemPrompt, definizione degli strumenti
│   │   ├── routes/            chat
│   │   └── services/          orchestrator (ReAct), verifier (controllo finale), dataAgent, sse, log, sessions, llm
│   └── test/
├── data_agent/                Python + FastAPI
│   ├── api.py                 endpoint, anche in streaming, e ricarica dei dati
│   ├── agente.py              agente LangChain e prompt
│   ├── strumenti.py           i 12 strumenti, con lo stato di ogni domanda separato
│   ├── caricamento.py         lettura dei CSV con errori chiari se sono malformati
│   ├── analisi.py             calcoli: incasso, sell-through, resi, margine, sconti, controlli
│   ├── pulizia.py             pulizia deterministica con resoconto
│   ├── calendario.py          date dei saldi e scaglioni
│   ├── grafici.py             grafici matplotlib/seaborn e pulizia dei PNG vecchi
│   ├── rag.py                 ChromaDB + BM25
│   ├── embedding.py           embedding multilingue in ONNX
│   ├── valuta_rag.py          confronto BM25 / embedding / fusione
│   ├── registro.py            log strutturati
│   └── tests/
├── .github/workflows/         test a ogni push
├── start.sh · Makefile        installazione e avvio in un comando
├── .env.example               l'unico file di configurazione
├── data/                      vendite.csv, ordini.csv, la_collina_kb.txt
├── valutazione/               dati di riferimento, registro anomalie, domande per valutare il RAG
└── notebooks/                 generatore, esplorazione, pulizia, risposte attese
```

---

## Limiti noti

- **Quota gratuita di Groq:** i due agenti usano modelli diversi, ognuno con il suo limite giornaliero di token. Una domanda ibrida ne consuma molti: bastano per una demo, non per un uso quotidiano in negozio.
- **Latenza:** 20–30 secondi per una domanda sui dati, fino a 60–70 per una ibrida. Il ciclo ReAct con due agenti in serie è il prezzo dell'orchestrazione.
- **Il modello resta un modello:** con i dati giusti in mano può ancora scegliere male cosa mettere in risposta (un'azione fuori tema, un confronto mancante). Le correzioni fatte sono nel prompt e negli strumenti, non garantite.
- **RAG sui sinonimi:** anche con l'embedding multilingue, 6 domande con sinonimi su 21 non trovano la sezione giusta tra le prime 6 (vedi *Scelte tecniche, 3*). Il passo successivo sarebbe un insieme di domande più ampio, scritto da chi lavora in negozio, per tarare la fusione senza adattarla al test.
- **Memoria in RAM:** sessioni e rate limit si azzerano a ogni riavvio del back end.
- **Dati generati:** i brand piantati con un problema rendono le scoperte prevedibili. Con dati reali, e il permesso del titolare, il valore sarebbe nelle scoperte che non ci si aspetta.

---

## Verso la produzione

Scelte giuste per un dimostratore, da cambiare prima di usarlo davvero in negozio:

| Tema | Oggi | In produzione |
|---|---|---|
| Archivio dei dati | due CSV letti in pandas all'avvio: 16.000 righe, meno di un secondo | **DuckDB** sui file (CSV o Parquet) se lo storico cresce o i negozi diventano più di uno: stesse analisi in SQL colonnare, senza server. **SQLite** se i dati arrivano dalla cassa riga per riga. Gli strumenti dell'agente non cambiano: cambia l'interno di `analisi.py` |
| Aggiornamento | `POST /ricarica` a mano | caricamento automatico, per esempio di notte dopo la chiusura di cassa |
| Sessioni e rate limit | in RAM, si azzerano a ogni riavvio | Redis, condiviso tra più istanze |
| Grafici | PNG su disco locale | storage condiviso, o grafici disegnati dal front end con i dati |
| Log | su standard output | `LOG_FORMAT=json` verso un sistema di raccolta log |

