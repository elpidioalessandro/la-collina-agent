import re
import time

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import BadRequestError, RateLimitError

import analisi
import config
import grafici
from registro import registro
from strumenti import STRUMENTI, nuova_domanda

log = registro("agente")
CHIEDE_GRAFICO = re.compile(r"grafic|mostrami|visualizza|fammi vedere|andamento", re.IGNORECASE)
FILTRI_GRAFICO = ("stagione", "brand", "categoria", "data_inizio", "data_fine", "motivo")

# Come si annuncia ogni strumento nei passi mostrati in chat mentre l'agente lavora.
PASSI = {
    "info_dati": "Controllo periodo, brand e stagioni disponibili",
    "incasso": "Calcolo l'incasso",
    "sell_through": "Calcolo il sell-through",
    "confronta_stagioni": "Confronto la stagione con quelle vicine",
    "soglie_fornitori": "Controllo le soglie dei fornitori",
    "resi": "Analizzo i resi",
    "margine": "Calcolo il margine",
    "sconti": "Analizzo gli sconti",
    "controlli_regole": "Incrocio i dati con le regole del negozio",
    "resoconto_pulizia": "Leggo il resoconto della pulizia dei dati",
    "crea_grafico": "Disegno il grafico",
    "esegui_codice_pandas": "Scrivo un calcolo su misura in pandas",
}


def descrivi_passo(nome: str, argomenti: dict) -> str:
    """«Analizzo i resi (Lardoni, AI24)»: il nome dello strumento in italiano, con i filtri principali."""
    dettagli = [str(argomenti[k]) for k in ("brand", "categoria", "stagione", "motivo") if argomenti.get(k)]
    testo = PASSI.get(nome, f"Uso lo strumento {nome}")
    return f"{testo} ({', '.join(dettagli)})" if dettagli else testo


def prompt_di_sistema(d: analisi.Dati) -> str:
    info = analisi.info_dati(d)
    saldi = "\n".join(f"  - {s}" for s in info["saldi"])
    return f"""Sei l'analista dati di La Collina, negozio multimarca di abbigliamento uomo nelle Marche.
Rispondi al titolare e ai commessi usando i dati di cassa e degli ordini, già puliti.

DATI
- Vendite dal {info['periodo_vendite'].replace(' / ', ' al ')}. Anni completi: {info['anni_completi']}; gli altri anni
  sono parziali e non si confrontano con quelli completi.
- Stagioni: PE = primavera-estate, AI = autunno-inverno, seguite dall'anno (AI24 = autunno-inverno 2024).
- Brand: {', '.join(info['brand'])}.
- Categorie: {', '.join(info['categorie'])}.
- Periodi di saldi:
{saldi}

COME LAVORI
1. I numeri vengono solo dagli strumenti: non inventare, non stimare, non fare calcoli a mente.
2. Preferisci gli strumenti specifici; usa esegui_codice_pandas solo se nessun altro basta.
   Se il codice dà errore, leggi il messaggio, correggi e riprova.
3. Se la domanda chiede un grafico ("mostrami", "grafico", "andamento", "visualizza", "fammi vedere"),
   usa crea_grafico (o esegui_codice_pandas con plt se il grafico richiesto non è previsto).
4. Se un brand, una stagione o un periodo non sono nei dati, dillo e indica cosa è disponibile.
5. I dati mostrano cosa è successo, non perché: non presentare una causa come certa. Se ipotizzi
   una spiegazione, chiamala ipotesi da verificare.
6. Per regole e procedure del negozio non rispondere tu: limitati ai dati.
7. Un dato su un brand o una categoria ha senso solo a confronto: confrontalo sempre con gli altri
   (resi, sell-through, margine per brand) e, per i resi, scomponilo per motivo.
8. Non dire mai che non ci sono violazioni senza aver chiamato controlli_regole.
9. Parole del negozio: cappotti, giubbotti e piumini = categoria "capospalla"; scarpe = "scarpe casual"
   o "scarpe eleganti"; maglioni = "maglia".
10. "È andato bene/male" detto di una categoria o di un brand riguarda le vendite: usa confronta_stagioni
   (per i cappotti nel 2024: stagione AI24, categoria capospalla) e riporta la sua sintesi. I resi e il
   margine solo se la domanda ne parla.
11. Per dire se un valore è alto o basso usa il campo rispetto_al_negozio e il dato del negozio che gli
   strumenti restituiscono; per dire che un brand è il più alto o il più basso usa solo posizione_tra_i_brand.
   Non fare il confronto a mente.
12. Se un brand va segnalato per rinegoziazione lo dicono solo soglie_fornitori e il campo segnalazione di
   confronta_stagioni: riporta il loro esito così com'è, con le soglie superate.

COME RISPONDI
- In italiano, frasi brevi, massimo 150 parole. Prima il numero chiave, poi cosa significa.
- Euro con il punto per le migliaia e la virgola per i decimali (es. 1.234,50 €); percentuali con una cifra decimale.
- Una tabella in markdown solo se confronti più di tre valori.
- Se hai usato numeri di un anno parziale, dillo.
- Se hai creato un grafico, non descriverlo: l'utente lo vede già. Riporta comunque i numeri chiave
  (il valore più alto e il più basso), presi dal risultato dello strumento.
- Ogni numero che scrivi deve comparire nel risultato di uno strumento.
- Prima di scrivere "sopra", "sotto", "più alto" o "inferiore", confronta le due cifre: "inferiore" solo
  se il numero è più piccolo dell'altro."""


def costruisci_llm() -> ChatOpenAI:
    return ChatOpenAI(model=config.LLM_MODEL, base_url=config.LLM_BASE_URL, api_key=config.GROQ_API_KEY,
                      temperature=0, max_tokens=2048, max_retries=2, reasoning_effort=config.LLM_REASONING_EFFORT)


def _testo(messaggio) -> str:
    contenuto = messaggio.content
    if isinstance(contenuto, list):
        contenuto = " ".join(b.get("text", "") for b in contenuto if isinstance(b, dict))
    return (contenuto or "").strip()


class AgenteDati:
    """Agente ReAct sui dati di La Collina: sceglie gli strumenti, li esegue e risponde.
    Non ha memoria: la conversazione la tiene il back end, che gli passa domande complete."""

    def __init__(self, dati: analisi.Dati, llm=None):
        self.dati = dati
        self.llm = llm or costruisci_llm()
        self.agente = create_agent(self.llm, STRUMENTI, system_prompt=prompt_di_sistema(dati))

    def _esegui(self, messaggi, al_passo) -> list:
        """Esegue il ciclo ReAct e restituisce i messaggi nuovi. Annuncia ogni strumento appena il modello lo sceglie."""
        visti, ultimo = len(messaggi), None
        for ultimo in self.agente.stream({"messages": messaggi}, {"recursion_limit": 16}, stream_mode="values"):
            tutti = ultimo["messages"]
            for m in tutti[visti:]:
                if isinstance(m, AIMessage):
                    for c in m.tool_calls:
                        log.debug("strumento scelto", extra={"strumento": c["name"], "argomenti": c["args"]})
                        if al_passo:
                            al_passo(descrivi_passo(c["name"], c["args"]))
            visti = len(tutti)
        return ultimo["messages"][len(messaggi):] if ultimo else []

    @staticmethod
    def _grafico_mancante(stato, passaggi, al_passo) -> None:
        """La domanda chiede un grafico ma il modello non l'ha creato: lo disegna il codice, con la stessa metrica,
        lo stesso raggruppamento e gli stessi filtri dell'ultimo calcolo fatto."""
        calcolo = next((p for p in reversed(passaggi) if p["strumento"] in grafici.METRICHE), None)
        if not calcolo:
            return
        argomenti = calcolo["argomenti"]
        raggruppa_per = argomenti.get("raggruppa_per") or "brand"
        if raggruppa_per in ("nessuno", "brand_motivo"):
            raggruppa_per = "brand"
        filtri = {k: argomenti[k] for k in FILTRI_GRAFICO if argomenti.get(k)}
        try:
            nome = grafici.crea_grafico(stato.dati, calcolo["strumento"], raggruppa_per, **filtri)
        except ValueError as e:
            log.warning("grafico automatico non riuscito", extra={"motivo": str(e)})
            return
        stato.grafici.append(nome)
        log.info("grafico creato dal codice", extra={"metrica": calcolo["strumento"], "raggruppa_per": raggruppa_per})
        if al_passo:
            al_passo("Disegno il grafico")

    def chiedi(self, domanda: str, al_passo=None) -> dict:
        """Risponde a una domanda sui dati. al_passo(testo), se c'è, riceve i passi mentre l'agente lavora."""
        suggerimento, errori, risposta, passaggi, risultati = "", [], "", [], []
        for tentativo in range(3):
            stato = nuova_domanda(self.dati)
            try:
                messaggi = [HumanMessage(domanda + suggerimento)]
                nuovi = self._esegui(messaggi, al_passo)
            except RateLimitError:
                errori.append(f"Tentativo {tentativo + 1}: limite di richieste di Groq, attendo 20 secondi")
                log.warning("limite di Groq", extra={"tentativo": tentativo + 1, "attesa_s": 20})
                if al_passo:
                    al_passo("Limite di richieste di Groq: riprovo tra 20 secondi")
                time.sleep(20)
                continue
            except BadRequestError as e:
                errori.append(f"Tentativo {tentativo + 1}: richiesta non valida ({str(e)[:150]})")
                log.warning("richiesta rifiutata da Groq", extra={"tentativo": tentativo + 1, "dettaglio": str(e)[:150]})
                suggerimento = ("\n\n[Nota] Usa solo gli strumenti elencati, con i nomi esatti. Per calcoli "
                                "personalizzati usa esegui_codice_pandas.")
                continue
            except Exception as e:
                errori.append(f"Errore imprevisto: {type(e).__name__}: {str(e)[:150]}")
                log.exception("errore imprevisto dell'agente", extra={"tentativo": tentativo + 1})
                break
            passaggi, risultati = [], []
            for m in nuovi:
                if isinstance(m, AIMessage):
                    passaggi += [{"strumento": c["name"], "argomenti": c["args"]} for c in m.tool_calls]
                elif isinstance(m, ToolMessage) and passaggi:
                    passaggi[-1]["esito"] = m.content[:300]
                    if not m.content.startswith("ERRORE"):
                        risultati.append(f"{m.name}: {m.content}")
            risposta = _testo(nuovi[-1]) if nuovi else ""
            if risposta:
                break
            errori.append(f"Tentativo {tentativo + 1}: risposta vuota del modello")
            log.warning("risposta vuota del modello", extra={"tentativo": tentativo + 1})
            suggerimento = "\n\n[Nota] Chiama subito gli strumenti necessari e poi rispondi in modo breve."
        if not risposta:
            risposta = "Al momento non riesco ad analizzare i dati. Riprova tra un minuto."
        elif not stato.grafici and CHIEDE_GRAFICO.search(domanda):
            self._grafico_mancante(stato, passaggi, al_passo)
        return {"risposta": risposta, "grafici": list(stato.grafici), "passaggi": passaggi,
                "risultati_strumenti": "\n".join(risultati)[:6000],
                "risultati_completi": "\n".join(risultati),
                "errori": errori, "nota_dati": analisi.nota_dati(self.dati)}
