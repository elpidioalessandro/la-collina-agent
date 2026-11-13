from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import analisi
import config

SERVIZI = {}


class DomandaManuale(BaseModel):
    domanda: str = Field(min_length=2, max_length=1000)
    k: int = Field(default=4, ge=1, le=8)


class DomandaDati(BaseModel):
    domanda: str = Field(min_length=2, max_length=1500)


def avvia(dati=None, manuale=None, agente=None):
    """Carica dati, manuale e agente. I parametri servono ai test per iniettare versioni finte."""
    from agente import AgenteDati
    from rag import Manuale

    SERVIZI["dati"] = dati or analisi.Dati.da_csv(config.VENDITE_CSV, config.ORDINI_CSV)
    SERVIZI["manuale"] = manuale or Manuale()
    SERVIZI["agente"] = agente or AgenteDati(SERVIZI["dati"])


@asynccontextmanager
async def ciclo_di_vita(app: FastAPI):
    if not SERVIZI:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY mancante: copia data_agent/.env.example in data_agent/.env")
        avvia()
    yield


app = FastAPI(title="La Collina – agente dati e manuale", lifespan=ciclo_di_vita)


@app.get("/salute")
def salute():
    d = SERVIZI["dati"]
    return {"stato": "ok", "righe_vendite": len(d.v), "righe_ordini": len(d.o),
            "sezioni_manuale": len(SERVIZI["manuale"].sezioni)}


@app.post("/cerca")
def cerca(richiesta: DomandaManuale):
    return {"domanda": richiesta.domanda, "risultati": SERVIZI["manuale"].cerca(richiesta.domanda, richiesta.k)}


@app.post("/analizza")
def analizza(richiesta: DomandaDati):
    esito = SERVIZI["agente"].chiedi(richiesta.domanda)
    return {**esito, "grafici": [{"nome": n, "url": f"/grafici/{n}"} for n in esito["grafici"]]}


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
