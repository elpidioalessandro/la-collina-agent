import time

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import BadRequestError, RateLimitError

import analisi
import config
from strumenti import STATO, STRUMENTI, imposta_dati, nuova_domanda


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

COME RISPONDI
- In italiano, frasi brevi, massimo 150 parole. Prima il numero chiave, poi cosa significa.
- Euro con il punto per le migliaia e la virgola per i decimali (es. 1.234,50 €); percentuali con una cifra decimale.
- Una tabella in markdown solo se confronti più di tre valori.
- Se hai usato numeri di un anno parziale, dillo.
- Se hai creato un grafico, non descriverlo: l'utente lo vede già. Riporta comunque i numeri chiave
  (il valore più alto e il più basso), presi dal risultato dello strumento.
- Ogni numero che scrivi deve comparire nel risultato di uno strumento."""


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
        imposta_dati(dati)
        self.dati = dati
        self.llm = llm or costruisci_llm()
        self.agente = create_agent(self.llm, STRUMENTI, system_prompt=prompt_di_sistema(dati))

    def chiedi(self, domanda: str) -> dict:
        suggerimento, errori, risposta, passaggi, risultati = "", [], "", [], []
        for tentativo in range(3):
            nuova_domanda()
            try:
                messaggi = [HumanMessage(domanda + suggerimento)]
                esito = self.agente.invoke({"messages": messaggi}, {"recursion_limit": 16})
            except RateLimitError:
                errori.append(f"Tentativo {tentativo + 1}: limite di richieste di Groq, attendo 20 secondi")
                time.sleep(20)
                continue
            except BadRequestError as e:
                errori.append(f"Tentativo {tentativo + 1}: richiesta non valida ({str(e)[:150]})")
                suggerimento = ("\n\n[Nota] Usa solo gli strumenti elencati, con i nomi esatti. Per calcoli "
                                "personalizzati usa esegui_codice_pandas.")
                continue
            except Exception as e:
                errori.append(f"Errore imprevisto: {type(e).__name__}: {str(e)[:150]}")
                break
            nuovi = esito["messages"][len(messaggi):]
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
            suggerimento = "\n\n[Nota] Chiama subito gli strumenti necessari e poi rispondi in modo breve."
        if not risposta:
            risposta = "Al momento non riesco ad analizzare i dati. Riprova tra un minuto."
        return {"risposta": risposta, "grafici": list(STATO["grafici"]), "passaggi": passaggi,
                "risultati_strumenti": "\n".join(risultati)[:6000],
                "errori": errori, "nota_dati": analisi.nota_dati(self.dati)}
