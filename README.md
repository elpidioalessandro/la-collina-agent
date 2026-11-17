# La Collina: un agente AI a supporto delle decisioni del punto vendita

Agente AI ibrido per un negozio multimarca di abbigliamento uomo. Commessi e titolare fanno domande in chat: l'LLM decide da solo se cercare la risposta nel **manuale del negozio** (RAG su ChromaDB) o affidarla a un **agente dati Python** che analizza vendite e ordini con pandas e disegna grafici. Per le domande che chiedono numeri e regole insieme usa entrambi.

Ogni risposta riporta le **sezioni del manuale** usate, una **nota sulla qualità dei dati** (righe usate, scartate e corrette) e gli **strumenti chiamati**.

> Negozio, brand, fornitori e dati sono di fantasia; eventuali omonimie sono casuali. Il progetto è ispirato a un negozio reale in cui ho lavorato come commesso.

---

## Architettura

```
 Browser (React)             Back end (Node + Express)                  Agente dati (Python + FastAPI)
┌──────────────────┐ POST  ┌────────────────────────────────┐  /cerca   ┌──────────────────────────────┐
│ chat + memoria   │──────▶│ /api/chat                      │──────────▶│ RAG: ChromaDB + BM25         │──▶ la_collina_kb.txt
│ "sta scrivendo"  │       │ sessione (ultimi 10 messaggi)  │           │                              │
│ grafici, fonti   │◀──────│ orchestratore ReAct            │ /analizza │ pulizia → agente pandas      │──▶ vendite.csv
│ "come ho         │ JSON  │ function calling:              │──────────▶│ (LangChain, 12 strumenti)    │──▶ ordini.csv
│  risposto"       │       │ cerca_manuale · analizza_dati  │◀──────────│ grafici PNG su disco         │
└──────────────────┘       └────────────────────────────────┘           └──────────────────────────────┘
     Vite :5173                     :3001   │                                      :8000   │
                                            └──── Groq (gpt-oss-120b · gpt-oss-20b) ───────┘
```

| Livello | Tecnologia |
|---|---|
| Front end | React 19, Vite, react-markdown |
| Back end | Node.js, Express 5, SDK `openai` (function calling nativo) |
| Agente dati | Python 3.12, FastAPI, pandas, LangChain (`create_agent`), matplotlib, seaborn |
| RAG | ChromaDB locale (embedding ONNX `all-MiniLM-L6-v2`) + BM25 |
| LLM | Groq, API compatibile OpenAI: `openai/gpt-oss-120b` per l'orchestratore, `openai/gpt-oss-20b` per l'agente dati |

**Perché due modelli e non uno.** L'orchestratore Node vede la conversazione e sceglie gli strumenti; l'agente dati Python vede solo una domanda alla volta, già riscritta in forma completa dall'orchestratore ("e Cruciverba?" diventa "Resi di Cruciverba per motivo, confrontati con gli altri brand"). Così la memoria vive in un posto solo e il servizio Python resta senza stato, facile da testare.

I due agenti usano due modelli diversi perché sul piano gratuito di Groq il limite di token al minuto (8.000) vale per modello: con un modello solo, una domanda ibrida lo superava e le risposte arrivavano oltre i 90 secondi. L'agente dati sceglie gli strumenti e passa i numeri, che arrivano già calcolati: basta il modello più piccolo. Il testo finale lo scrive l'orchestratore, sul modello più grande.

---

## API

### Back end (`:3001`)
| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/chat` | `{ "message": "...", "sessionId": "..." }`; senza `sessionId` ne crea uno |
| `DELETE` | `/api/chat/:sessionId` | Cancella la memoria della conversazione |
| `GET` | `/api/grafici/:nome` | Proxy verso il grafico PNG creato dall'agente dati |
| `GET` | `/api/health` | Stato del back end e dell'agente dati |

Risposta di `POST /api/chat`:

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
| `GET` | `/resoconto-pulizia` | Tutte le correzioni fatte ai dati |
| `GET` | `/grafici/:nome` | File PNG |
| `GET` | `/salute` | Righe caricate e sezioni del manuale |

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

---

## Scelte tecniche

### 1. Pulizia deterministica prima dell'LLM
I dati non arrivano mai sporchi al modello. `data_agent/pulizia.py` applica una ventina di regole in un ordine preciso (prima i duplicati, poi date, prezzi, sconti ricalcolati dal prezzo pagato, prezzi mancanti ricostruiti da listino e sconto, motivi dedotti da sconto e data) e restituisce un **resoconto** con le righe toccate da ogni regola. Le stesse regole sono scritte in italiano nella Parte 10 del manuale, così l'agente può spiegare *perché* ha corretto un dato.

Verifica sul riferimento (`notebooks/pulizia.ipynb`): su 16.405 × 19 celle di vendite e 4.511 × 15 di ordini **resta una sola cella diversa**, un codice articolo con due candidati possibili che la pulizia sceglie di non indovinare.

### 2. I numeri vengono solo dagli strumenti
L'agente dati non calcola a mente: ha 12 strumenti (`incasso`, `sell_through`, `confronta_stagioni`, `soglie_fornitori`, `resi`, `margine`, `sconti`, `controlli_regole`, `resoconto_pulizia`, `crea_grafico`, `info_dati`, `esegui_codice_pandas`). Il codice pandas libero è l'ultima risorsa, con un massimo di 3 tentativi e l'errore restituito al modello perché si corregga.

All'orchestratore arrivano sia la risposta dell'agente dati sia i **risultati grezzi degli strumenti**, con una regola esplicita: si possono usare solo quei numeri. È la correzione a un errore trovato nei test: quando l'agente dati creava solo il grafico senza leggere i valori, l'orchestratore "riempiva" la risposta con numeri plausibili e inventati.

Anche i confronti arrivano già calcolati: `resi`, `sell_through` e `margine` restituiscono il dato complessivo del negozio e, riga per riga, se il valore è sopra o sotto; `confronta_stagioni` restituisce una stagione contro la stessa stagione dell'anno prima e dopo, con le differenze. Il modello copia il confronto invece di farlo a mente, perché nei test scriveva "inferiore" accanto a un numero più grande.

**Controllo finale della risposta** (`backend/src/services/verifier.js`). Prima dell'invio il codice, non il modello, verifica tre cose:

| Verifica | Se fallisce |
|---|---|
| Ogni numero della risposta compare nei risultati degli strumenti, nel manuale letto o nella domanda (con tolleranza sugli arrotondamenti) | la risposta torna al modello con l'elenco dei numeri non trovati |
| Ogni sezione citata, in qualsiasi forma (`[SEZ 8.6]`, `(SEZ 8.6)`, `【SEZ 8.6】`), è stata letta | se la sezione esiste viene letta e il modello ricontrolla cosa le attribuisce; se non esiste, la citazione sparisce |
| Il manuale si nomina solo se è stato consultato | la risposta torna al modello |

Il modello ha una sola seconda possibilità: se sbaglia ancora, le frasi con numeri o fonti non verificati vengono tolte. L'esito del controllo compare in *Come ho risposto* e nel log del back end.

### 3. RAG ibrido: significato + parole
Il modello di embedding di ChromaDB è addestrato sull'inglese e sull'italiano è debole. La ricerca affianca a ChromaDB un indice **BM25** sulle stesse sezioni (parole ridotte alle prime 5 lettere, così *profumo* e *profumi* coincidono) e fonde le due classifiche con **Reciprocal Rank Fusion**. Con la sola ricerca per parole, la sezione giusta è tra le prime 3 in 17 domande di prova su 17; i test automatici ne controllano 12.

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
| Risposta oltre i 60 s (Safari chiude le richieste inattive) | il back end apre subito la risposta e invia uno spazio ogni 10 s |

### 6. Sicurezza
| Rischio | Contromisura |
|---|---|
| Chiave API esposta | solo nei file `.env`, esclusi da git; nel repo ci sono solo i `.env.example` |
| Quota esaurita da uno script | rate limit: 10 domande al minuto per IP, 300 al giorno in totale |
| Path traversal sui grafici | Node accetta solo nomi nel formato `[0-9a-f]{12}.png`; Python serve solo file `.png` della cartella dei grafici |
| Domande enormi | massimo 1.000 caratteri, corpo JSON massimo 20 kB |
| Dati personali | nessun dato su clienti identificati o singoli dipendenti; l'agente lo dichiara se glieli chiedono |

### 7. Test
Nessun test chiama Groq: l'LLM è sostituito da modelli finti che seguono un copione.

| Suite | Test | Cosa verifica |
|---|---|---|
| `data_agent/tests` (pytest) | 33 | pulizia uguale al riferimento, risposte attese (sell-through, resi, controlli, confronto tra stagioni, confronti con il negozio, soglie del sell-through spiegate come nel manuale, brand da segnalare secondo la SEZ 8.6), errori leggibili, limite di tentativi del codice, grafici salvati, RAG su 12 domande, agente e API con LLM finto |
| `backend/test` (node:test) | 22 | orchestratore: scelta degli strumenti, domande ibride, memoria, retry su 400 e 429, limite di passaggi, agente dati spento; controllo finale: numeri inventati, sezioni non lette, manuale non consultato, citazioni in ogni forma senza unire le righe, numeri scritti dall'agente dati non accettati come fonte; HTTP: validazione, sessione, proxy dei grafici |

---

## Avvio in locale

Prerequisiti: Python 3.12, Node.js ≥ 20, una API key gratuita di [Groq](https://console.groq.com/keys).

Servono tre terminali, uno per servizio.

### 1. Agente dati (Python)
```bash
cd data_agent
python -m venv .venv && source .venv/bin/activate   # oppure un ambiente conda
pip install -r requirements.txt
cp .env.example .env          # inserisci GROQ_API_KEY
pytest -q                     # 33 test
python api.py                 # http://127.0.0.1:8000
```
Al primo avvio ChromaDB scarica il modello di embedding (circa 80 MB).

### 2. Back end (Node)
```bash
cd backend
npm install
cp .env.example .env          # inserisci GROQ_API_KEY
npm test                      # 22 test
npm start                     # http://localhost:3001
```

### 3. Front end (React)
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

### Variabili d'ambiente
`data_agent/.env`:
```
GROQ_API_KEY=
LLM_MODEL=openai/gpt-oss-20b
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_REASONING_EFFORT=low
PORT=8000
```

`backend/.env`:
```
GROQ_API_KEY=
LLM_MODEL=openai/gpt-oss-120b
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_REASONING_EFFORT=low
DATA_AGENT_URL=http://127.0.0.1:8000
PORT=3001
CORS_ORIGIN=http://localhost:5173
```

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
│       └── lib/               api, storage
├── backend/                   Node + Express
│   ├── src/
│   │   ├── config/            env
│   │   ├── middleware/        rateLimit, errorHandler
│   │   ├── prompts/           systemPrompt, definizione degli strumenti
│   │   ├── routes/            chat
│   │   └── services/          orchestrator (ReAct), verifier (controllo finale), dataAgent, sessions, llm
│   └── test/
├── data_agent/                Python + FastAPI
│   ├── api.py                 endpoint
│   ├── agente.py              agente LangChain e prompt
│   ├── strumenti.py           i 10 strumenti
│   ├── analisi.py             calcoli: incasso, sell-through, resi, margine, sconti, controlli
│   ├── pulizia.py             pulizia deterministica con resoconto
│   ├── calendario.py          date dei saldi e scaglioni
│   ├── grafici.py             grafici matplotlib/seaborn
│   ├── rag.py                 ChromaDB + BM25
│   └── tests/
├── data/                      vendite.csv, ordini.csv, la_collina_kb.txt
├── valutazione/               dati di riferimento e registro anomalie (solo per i test)
└── notebooks/                 generatore, esplorazione, pulizia, risposte attese
```

---

## Limiti noti

- **Quota gratuita di Groq:** i due agenti usano lo stesso modello e si dividono il limite giornaliero di token. Una domanda ibrida ne consuma molti: bastano per una demo, non per un uso quotidiano in negozio.
- **Latenza:** 20–30 secondi per una domanda sui dati, fino a 60–70 per una ibrida. Il ciclo ReAct con due agenti in serie è il prezzo dell'orchestrazione.
- **Il modello resta un modello:** con i dati giusti in mano può ancora scegliere male cosa mettere in risposta (un'azione fuori tema, un confronto mancante). Le correzioni fatte sono nel prompt e negli strumenti, non garantite.
- **Embedding inglese:** la qualità del RAG sull'italiano si regge sul BM25. Un modello multilingue migliorerebbe la parte semantica, al costo di installare PyTorch.
- **Memoria in RAM:** sessioni e rate limit si azzerano a ogni riavvio del back end.
- **Dati generati:** i brand piantati con un problema rendono le scoperte prevedibili. Con dati reali, e il permesso del titolare, il valore sarebbe nelle scoperte che non ci si aspetta.
