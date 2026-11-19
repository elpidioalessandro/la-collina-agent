from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import api
import config
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


def test_due_agenti_in_parallelo(dati):
    """Due domande contemporanee all'agente: ognuna riceve solo i suoi grafici."""
    from concurrent.futures import ThreadPoolExecutor

    def chiedi(metrica):
        llm = llm_con_copione(
            chiamata("crea_grafico", {"metrica": metrica, "raggruppa_per": "brand"}),
            AIMessage(content=f"Grafico di {metrica}."),
        )
        return AgenteDati(dati, llm=llm).chiedi(f"Grafico {metrica} per brand")

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(chiedi, ["resi", "margine"])
    assert len(a["grafici"]) == 1 and len(b["grafici"]) == 1
    assert a["grafici"] != b["grafici"]
    assert a["passaggi"][0]["argomenti"]["metrica"] == "resi"


def _client_con_copione(dati, manuale, *messaggi):
    api.SERVIZI.clear()
    api.avvia(dati=dati, manuale=manuale, agente=AgenteDati(dati, llm=llm_con_copione(*messaggi)))
    return TestClient(api.app)


def test_streaming_passi_poi_risultato(dati, manuale):
    import json

    client = _client_con_copione(dati, manuale, chiamata("resi", {"raggruppa_per": "brand", "brand": "Lardoni"}),
                                 AIMessage(content="Lardoni: 4,7%."))
    with client, client.stream("POST", "/analizza/stream", json={"domanda": "Resi di Lardoni"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        eventi = [blocco for blocco in r.read().decode().split("\n\n") if blocco.startswith("event:")]
    tipi = [e.split("\n")[0].removeprefix("event: ") for e in eventi]
    assert tipi == ["passo", "risultato"]
    assert json.loads(eventi[0].split("data: ", 1)[1]) == {"testo": "Analizzo i resi (Lardoni)"}
    risultato = json.loads(eventi[1].split("data: ", 1)[1])
    assert risultato["risposta"] == "Lardoni: 4,7%." and risultato["passaggi"][0]["strumento"] == "resi"


def test_ricarica_dei_dati(dati, manuale, tmp_path, monkeypatch):
    import shutil

    client = _client_con_copione(dati, manuale)
    copia_vendite, copia_ordini = tmp_path / "vendite.csv", tmp_path / "ordini.csv"
    shutil.copy(config.VENDITE_CSV, copia_vendite)
    shutil.copy(config.ORDINI_CSV, copia_ordini)
    monkeypatch.setattr(config, "VENDITE_CSV", copia_vendite)
    monkeypatch.setattr(config, "ORDINI_CSV", copia_ordini)
    with client:
        assert client.get("/salute").json()["file_cambiati"] is True  # i percorsi ora puntano ai file copiati
        ok = client.post("/ricarica").json()
        assert ok["stato"] == "ricaricati" and ok["righe_vendite"] == len(dati.v)
        assert client.get("/salute").json()["file_cambiati"] is False
        copia_ordini.write_text("")
        rifiutata = client.post("/ricarica")
        assert rifiutata.status_code == 422
        assert "restano quelli di prima" in rifiutata.json()["detail"] and "ordini: il file è vuoto" in rifiutata.json()["detail"]
        assert client.get("/salute").json()["righe_vendite"] == len(dati.v)


def test_log_strutturato(capsys):
    import logging

    import registro

    log = registro.configura(formato="testo")
    registro.ID_RICHIESTA.set("abc12345")
    logging.getLogger("la_collina.api").info("analizza", extra={"durata_s": 1.5, "domanda": 'resi "Lardoni"'})
    riga = capsys.readouterr().out.strip()
    assert riga.endswith('INFO analizza id=abc12345 durata_s=1.5 domanda="resi \\"Lardoni\\""')
    registro.configura(formato="json")
    logging.getLogger("la_collina.api").warning("ricarica rifiutata", extra={"motivo": "file vuoto"})
    voce = __import__("json").loads(capsys.readouterr().out)
    assert voce["livello"] == "WARNING" and voce["evento"] == "ricarica rifiutata" and voce["motivo"] == "file vuoto"
    registro.configura(formato="testo")
    assert log.name == "la_collina"


def test_grafico_chiesto_ma_dimenticato_lo_crea_il_codice(dati):
    passi = []
    llm = llm_con_copione(chiamata("sell_through", {"raggruppa_per": "brand"}), AIMessage(content="Ecco il sell-through."))
    esito = AgenteDati(dati, llm=llm).chiedi("Sell-through per brand con grafico", al_passo=passi.append)
    assert len(esito["grafici"]) == 1 and passi[-1] == "Disegno il grafico"
    llm = llm_con_copione(chiamata("sell_through", {"raggruppa_per": "brand"}), AIMessage(content="Ecco il sell-through."))
    assert AgenteDati(dati, llm=llm).chiedi("Sell-through per brand")["grafici"] == []
