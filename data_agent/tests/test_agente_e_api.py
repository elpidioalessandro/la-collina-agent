from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import api
from agente import AgenteDati
from finti import chiamata, llm_con_copione


def test_agente_usa_lo_strumento_e_crea_il_grafico(dati):
    llm = llm_con_copione(
        chiamata("crea_grafico", {"metrica": "sell_through", "raggruppa_per": "brand"}),
        AIMessage(content="Il sell-through più basso è di Lido Club (56,2%)."),
    )
    esito = AgenteDati(dati, llm=llm).chiedi("Mostrami il sell-through per brand")
    assert esito["risposta"].startswith("Il sell-through più basso")
    assert esito["passaggi"][0]["strumento"] == "crea_grafico"
    assert len(esito["grafici"]) == 1 and "righe duplicate scartate" in esito["nota_dati"]


def test_api(dati, manuale):
    llm = llm_con_copione(chiamata("incasso", {"raggruppa_per": "anno"}), AIMessage(content="Incasso 2025: 606.127,75 €."))
    api.SERVIZI.clear()
    api.avvia(dati=dati, manuale=manuale, agente=AgenteDati(dati, llm=llm))
    with TestClient(api.app) as client:
        assert client.get("/salute").json()["sezioni_manuale"] == 54
        cerca = client.post("/cerca", json={"domanda": "I profumi vanno in saldo?"}).json()
        assert cerca["risultati"][0]["codice"] == "SEZ 4.6"
        risposta = client.post("/analizza", json={"domanda": "Incasso per anno"}).json()
        assert risposta["risposta"].startswith("Incasso 2025") and risposta["grafici"] == []
        assert client.get("/grafici/../../config.py").status_code == 404
        assert client.post("/cerca", json={"domanda": ""}).status_code == 422
        sezioni = client.post("/sezioni", json={"codici": ["SEZ 8.6", "9.1", "SEZ 99.9"]}).json()["risultati"]
        assert [s["codice"] for s in sezioni] == ["SEZ 8.6", "SEZ 9.1"]
