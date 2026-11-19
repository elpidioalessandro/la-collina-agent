import contextvars
import json
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import analisi
import config
import grafici
import registro
from caricamento import ErroreDati

registro.configura()
log = registro.registro("api")
SERVIZI = {}
ATTESA_EVENTI_S = 10


class DomandaManuale(BaseModel):
    domanda: str = Field(min_length=2, max_length=1000)
    k: int = Field(default=4, ge=1, le=8)


class CodiciSezioni(BaseModel):
    codici: list[str] = Field(min_length=1, max_length=20)


class DomandaDati(BaseModel):
    domanda: str = Field(min_length=2, max_length=1500)


def _impronta_file() -> dict:
    return {nome: p.stat().st_mtime if p.is_file() else None
            for nome, p in (("vendite", Path(config.VENDITE_CSV)), ("ordini", Path(config.ORDINI_CSV)))}


def _carica_dati() -> analisi.Dati:
    inizio = time.time()
    dati = analisi.Dati.da_csv(config.VENDITE_CSV, config.ORDINI_CSV)
    SERVIZI["caricati"] = {"alle": datetime.now().isoformat(timespec="seconds"), "file": _impronta_file()}
    log.info("dati caricati", extra={"righe_vendite": len(dati.v), "righe_ordini": len(dati.o),
                                     "durata_s": round(time.time() - inizio, 1)})
    return dati


def avvia(dati=None, manuale=None, agente=None):
    """Carica dati, manuale e agente. I parametri servono ai test per iniettare versioni finte."""
    from agente import AgenteDati
    from rag import Manuale

    if dati is None:
        dati = _carica_dati()
    else:
        SERVIZI["caricati"] = {"alle": datetime.now().isoformat(timespec="seconds"), "file": _impronta_file()}
    SERVIZI["dati"] = dati
    SERVIZI["manuale"] = manuale or Manuale()
    SERVIZI["agente"] = agente or AgenteDati(dati)
    log.info("manuale caricato", extra={"sezioni": len(SERVIZI["manuale"].sezioni)})
    grafici.pulisci_vecchi()


@asynccontextmanager
async def ciclo_di_vita(app: FastAPI):
    if not SERVIZI:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY mancante: copia .env.example in .env nella cartella principale "
                               "e inserisci la chiave.")
        try:
            avvia()
        except ErroreDati as e:
            raise RuntimeError(f"Dati non caricati: {e}") from None
    yield


app = FastAPI(title="La Collina – agente dati e manuale", lifespan=ciclo_di_vita)


@app.get("/salute")
def salute():
    d = SERVIZI["dati"]
    caricati = SERVIZI.get("caricati", {})
    return {"stato": "ok", "righe_vendite": len(d.v), "righe_ordini": len(d.o),
            "sezioni_manuale": len(SERVIZI["manuale"].sezioni),
            "dati_caricati_alle": caricati.get("alle"),
            # True se i CSV sono cambiati dopo il caricamento: basta chiamare POST /ricarica.
            "file_cambiati": caricati.get("file") != _impronta_file()}


@app.post("/ricarica")
def ricarica():
    """Rilegge e ripulisce i CSV senza riavviare il servizio. Se i file nuovi sono malformati, restano i dati
    di prima e la risposta spiega cosa non va."""
    from agente import AgenteDati

    try:
        dati = _carica_dati()
    except ErroreDati as e:
        log.warning("ricarica rifiutata", extra={"motivo": str(e)})
        raise HTTPException(status_code=422, detail=f"Dati non ricaricati, restano quelli di prima: {e}") from None
    # Le domande già in corso finiscono con i dati vecchi; le nuove usano il nuovo agente.
    SERVIZI["agente"] = AgenteDati(dati, llm=SERVIZI["agente"].llm)
    SERVIZI["dati"] = dati
    return {"stato": "ricaricati", "righe_vendite": len(dati.v), "righe_ordini": len(dati.o),
            "dati_caricati_alle": SERVIZI["caricati"]["alle"]}


@app.post("/cerca")
def cerca(richiesta: DomandaManuale):
    return {"domanda": richiesta.domanda, "risultati": SERVIZI["manuale"].cerca(richiesta.domanda, richiesta.k)}


@app.post("/sezioni")
def sezioni(richiesta: CodiciSezioni):
    """Sezioni del manuale per codice ("SEZ 8.6" o "8.6"): servono al controllo finale delle citazioni."""
    per_id = SERVIZI["manuale"].per_id
    trovate = [per_id[c.replace("SEZ", "").strip()] for c in richiesta.codici if c.replace("SEZ", "").strip() in per_id]
    return {"risultati": [{k: s[k] for k in ("codice", "titolo", "parte", "testo")} for s in trovate]}


def _analizza(domanda: str, al_passo=None) -> dict:
    """Una domanda all'agente dati, con il suo id di richiesta nei log."""
    registro.ID_RICHIESTA.set(uuid.uuid4().hex[:8])
    inizio = time.time()
    esito = SERVIZI["agente"].chiedi(domanda, al_passo=al_passo)
    log.info("analizza", extra={
        "durata_s": round(time.time() - inizio, 1),
        "strumenti": "+".join(p["strumento"] for p in esito["passaggi"]) or "nessuno",
        "grafici": len(esito["grafici"]), "errori": len(esito["errori"]),
        "domanda": domanda[:80]})
    for errore in esito["errori"]:
        log.warning("errore durante l'analisi", extra={"dettaglio": errore})
    return {**esito, "grafici": [{"nome": n, "url": f"/grafici/{n}"} for n in esito["grafici"]]}


@app.post("/analizza")
def analizza(richiesta: DomandaDati):
    return _analizza(richiesta.domanda)


def _evento(tipo: str, dati) -> str:
    return f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False, default=str)}\n\n"


@app.post("/analizza/stream")
def analizza_stream(richiesta: DomandaDati):
    """Come /analizza, ma in Server-Sent Events: un evento "passo" per ogni strumento scelto dall'agente,
    poi "risultato" con la risposta completa (o "errore")."""
    coda: queue.Queue = queue.Queue()

    def lavoro():
        try:
            coda.put(("risultato", _analizza(richiesta.domanda, al_passo=lambda t: coda.put(("passo", {"testo": t})))))
        except Exception as e:
            log.exception("analisi in streaming fallita")
            coda.put(("errore", {"errore": f"{type(e).__name__}: {str(e)[:200]}"}))
        finally:
            coda.put(None)

    threading.Thread(target=contextvars.copy_context().run, args=(lavoro,), daemon=True).start()

    def eventi():
        while True:
            try:
                voce = coda.get(timeout=ATTESA_EVENTI_S)
            except queue.Empty:
                yield ": in corso\n\n"  # commento SSE: tiene viva la connessione mentre il modello ragiona
                continue
            if voce is None:
                return
            yield _evento(*voce)

    return StreamingResponse(eventi(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/resoconto-pulizia")
def resoconto():
    return analisi.resoconto_pulizia(SERVIZI["dati"])


@app.get("/grafici/{nome}")
def grafico(nome: str):
    percorso = Path(config.CHART_DIR) / Path(nome).name
    if percorso.suffix != ".png" or not percorso.is_file():
        raise HTTPException(status_code=404, detail="Grafico non trovato")
    return FileResponse(percorso, media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=config.PORT)
