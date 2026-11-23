"""Archivio SQLite dei movimenti grezzi e base analitica DuckDB."""
import json
import shutil
import threading

import pandas as pd
import pytest

import analisi
import config
from archivio import Archivio
from caricamento import ErroreDati

ATTESI = config.ROOT_DIR / "valutazione" / "analisi_attese.json"

VENDITA = {"id_riga": "99999", "data_ora": "2025-12-15 11:00:00", "scontrino": "S2025-999999", "articolo": "LAR-GIA-001",
           "brand": "Lardoni", "categoria": "giacca", "taglia": "50", "stagione": "AI25", "prezzo_listino": "300.0",
           "prezzo_venduto": "300.0", "sconto_pct": "0", "motivo_sconto": "nessuno", "tipo_movimento": "vendita",
           "metodo_pagamento": "carta"}


def test_le_analisi_in_duckdb_danno_gli_stessi_numeri_della_versione_pandas(dati):
    """69 casi (incasso, sell-through, resi, margine con filtri e raggruppamenti diversi, ed errori) salvati
    dalla versione pandas prima del passaggio a DuckDB: devono restare identici."""
    casi = json.loads(ATTESI.read_text(encoding="utf-8"))
    assert len(casi) == 69
    for caso in casi:
        try:
            esito = json.loads(json.dumps(getattr(analisi, caso["funzione"])(dati, **caso["argomenti"]), default=str,
                                          ensure_ascii=False))
        except Exception as e:
            esito = {"errore": f"{type(e).__name__}: {e}"}
        for riga in esito.get("tabella", []):
            riga.pop("pct_sui_resi", None)  # colonna aggiunta dopo il passaggio, verificata nel test sotto
        assert esito == caso["esito"], f"{caso['funzione']}({caso['argomenti']})"


def test_resi_per_motivo_con_la_quota_sul_totale_dei_resi(dati):
    esito = analisi.resi(dati, raggruppa_per="motivo", brand="Lardoni")
    quote = {r["motivo_reso"]: r["pct_sui_resi"] for r in esito["tabella"]}
    assert esito["totale_resi"] == 105 and quote["taglia"] == 69.52  # 73 resi su 105, non "73%"
    assert sum(quote.values()) == pytest.approx(100, abs=0.05)


def test_archivio_importa_una_volta_e_rilegge_le_stesse_righe(tmp_path, dati):
    archivio = Archivio(tmp_path / "a.sqlite")
    assert archivio.importa_csv(config.VENDITE_CSV, "vendite") == 16569
    assert archivio.importa_csv(config.VENDITE_CSV, "vendite") == 0  # file uguale: niente da fare
    archivio.importa_csv(config.ORDINI_CSV, "ordini")
    dall_archivio = analisi.Dati.da_archivio(archivio)
    pd.testing.assert_frame_equal(dall_archivio.v, dati.v)
    pd.testing.assert_frame_equal(dall_archivio.o, dati.o)
    pd.testing.assert_frame_equal(dall_archivio.resoconto, dati.resoconto)


def test_riga_della_cassa_entra_nelle_analisi_e_sopravvive_al_nuovo_csv(tmp_path, dati):
    archivio = Archivio(tmp_path / "a.sqlite")
    csv = tmp_path / "vendite.csv"
    shutil.copy(config.VENDITE_CSV, csv)
    archivio.importa_csv(csv, "vendite")
    archivio.importa_csv(config.ORDINI_CSV, "ordini")
    assert archivio.registra("vendite", [VENDITA]) == 1
    prima = analisi.incasso(dati, brand="Lardoni")["tabella"][0]["pezzi"]
    dopo = analisi.incasso(analisi.Dati.da_archivio(archivio), brand="Lardoni")["tabella"][0]["pezzi"]
    assert dopo == prima + 1
    csv.write_text(csv.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # il CSV cambia: si reimporta
    assert archivio.importa_csv(csv, "vendite") == 16569
    assert archivio.conteggi()["vendite"] == {"csv": 16569, "cassa": 1}


def test_archivio_rifiuta_righe_sbagliate(tmp_path):
    archivio = Archivio(tmp_path / "a.sqlite")
    with pytest.raises(ErroreDati, match=r"Riga 1: colonne sconosciute \['colore_preferito'\]"):
        archivio.registra("vendite", [{**VENDITA, "colore_preferito": "blu"}])
    with pytest.raises(ErroreDati, match="Riga 2: mancano prezzo_venduto"):
        archivio.registra("vendite", [VENDITA, {k: v for k, v in VENDITA.items() if k != "prezzo_venduto"}])
    assert archivio.conteggi()["vendite"] == {}  # nessuna riga a metà


def test_duckdb_su_file_ricaricato_mentre_si_legge(tmp_path):
    percorso = tmp_path / "analitico.duckdb"
    primo = analisi.Dati.da_csv(config.VENDITE_CSV, config.ORDINI_CSV, percorso)
    atteso = analisi.resi(primo, "brand")
    secondo = analisi.Dati.da_csv(config.VENDITE_CSV, config.ORDINI_CSV, percorso)
    assert [p.name for p in tmp_path.glob("analitico-*.duckdb")] == [secondo.db.percorso.name]
    assert analisi.resi(primo, "brand") == atteso  # chi aveva il file vecchio continua a leggerlo
    assert analisi.resi(secondo, "brand") == atteso


def test_query_duckdb_in_parallelo(dati):
    attesi = {"resi": analisi.resi(dati, "brand"), "incasso": analisi.incasso(dati, "mese"),
              "margine": analisi.margine(dati, "categoria"), "sell": analisi.sell_through(dati, "brand")}
    funzioni = {"resi": lambda: analisi.resi(dati, "brand"), "incasso": lambda: analisi.incasso(dati, "mese"),
                "margine": lambda: analisi.margine(dati, "categoria"), "sell": lambda: analisi.sell_through(dati, "brand")}
    errori = []

    def lavoro(nome):
        for _ in range(5):
            if funzioni[nome]() != attesi[nome]:
                errori.append(nome)

    fili = [threading.Thread(target=lavoro, args=(n,)) for n in funzioni for _ in range(2)]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    assert errori == []
