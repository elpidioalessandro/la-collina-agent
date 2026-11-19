"""CSV malformati: ogni caso dà un errore che dice quale file e cosa correggere, invece di un KeyError a metà pulizia."""
import pandas as pd
import pytest

import analisi
import config
from caricamento import COLONNE_VENDITE, ErroreDati, leggi_ordini, leggi_vendite
from pulizia import pulisci

INTESTAZIONE = ",".join(COLONNE_VENDITE)
RIGA = "1,2024-03-10 11:00:00,S2024-000001,A,Lardoni,giacca,50,blu,AI23,100.0,80,20,saldo,vendita,,,,carta,,"


def scrivi(tmp_path, testo, nome="vendite.csv", codifica="utf-8"):
    p = tmp_path / nome
    p.write_bytes(testo.encode(codifica))
    return p


def test_file_mancante(tmp_path):
    with pytest.raises(ErroreDati, match="vendite: file non trovato"):
        leggi_vendite(tmp_path / "non_c_e.csv")


def test_file_vuoto(tmp_path):
    with pytest.raises(ErroreDati, match="vendite: il file è vuoto"):
        leggi_vendite(scrivi(tmp_path, ""))


def test_solo_intestazione(tmp_path):
    with pytest.raises(ErroreDati, match="solo l'intestazione"):
        leggi_vendite(scrivi(tmp_path, INTESTAZIONE + "\n"))


def test_separatore_punto_e_virgola(tmp_path):
    testo = INTESTAZIONE.replace(",", ";") + "\n" + RIGA.replace(",", ";") + "\n"
    with pytest.raises(ErroreDati, match="punto e virgola"):
        leggi_vendite(scrivi(tmp_path, testo))


def test_colonna_mancante(tmp_path):
    colonne = [c for c in COLONNE_VENDITE if c != "prezzo_listino"]
    valori = RIGA.split(",")
    valori.pop(COLONNE_VENDITE.index("prezzo_listino"))
    with pytest.raises(ErroreDati, match="mancano le colonne prezzo_listino"):
        leggi_vendite(scrivi(tmp_path, ",".join(colonne) + "\n" + ",".join(valori) + "\n"))


def test_riga_con_campi_in_piu(tmp_path):
    with pytest.raises(ErroreDati, match="non è un CSV valido"):
        leggi_vendite(scrivi(tmp_path, INTESTAZIONE + "\n" + RIGA + "\n" + RIGA + ",x,y\n"))


def test_valore_non_numerico(tmp_path):
    rotta = RIGA.replace(",100.0,", ",cento,")
    with pytest.raises(ErroreDati, match=r"prezzo_listino ha 1 valori non numerici \(il primo alla riga 3: 'cento'\)"):
        leggi_vendite(scrivi(tmp_path, INTESTAZIONE + "\n" + RIGA + "\n" + rotta + "\n"))


def test_codifica_non_utf8(tmp_path):
    testo = INTESTAZIONE + "\n" + RIGA.replace("Lardoni", "Lardonì") + "\n"
    with pytest.raises(ErroreDati, match="non è in UTF-8"):
        leggi_vendite(scrivi(tmp_path, testo, codifica="latin-1"))


def test_ordini_controllati_allo_stesso_modo(tmp_path):
    with pytest.raises(ErroreDati, match="ordini: mancano le colonne"):
        leggi_ordini(scrivi(tmp_path, "articolo,taglia\nA,50\n", nome="ordini.csv"))


def test_da_csv_con_un_file_rotto(tmp_path):
    with pytest.raises(ErroreDati, match="ordini: il file è vuoto"):
        analisi.Dati.da_csv(config.VENDITE_CSV, scrivi(tmp_path, "", nome="ordini.csv"))


def test_date_illeggibili_scartate_e_dichiarate():
    righe = pd.DataFrame({
        "id_riga": [1, 2], "data_ora": ["2024-03-10 11:00:00", "ieri sera"],
        "scontrino": ["S2024-000001", "S2024-000002"], "articolo": ["A", "A"], "brand": ["Lardoni"] * 2,
        "categoria": ["giacca"] * 2, "taglia": ["50"] * 2, "colore": ["blu"] * 2, "stagione": ["AI23"] * 2,
        "prezzo_listino": [100.0, 100.0], "prezzo_venduto": ["100", "100"], "sconto_pct": [0, 0],
        "motivo_sconto": ["nessuno", "nessuno"], "tipo_movimento": ["vendita"] * 2,
    })
    ordini = pd.DataFrame({"id_ordine": [1], "articolo": ["A"], "taglia": ["50"], "brand": ["Lardoni"],
                           "categoria": ["giacca"], "colore": ["blu"], "stagione": ["AI23"],
                           "data_ordine": ["2023-05-01"], "data_arrivo": ["2023-09-01"], "qta_ordinata": [2],
                           "qta_ricevuta": [2], "costo_unitario": [40.0], "prezzo_listino": [100.0]})
    v, _, resoconto = pulisci(righe, ordini)
    assert v["id_riga"].tolist() == [1]
    riga = resoconto[resoconto["regola"] == "date illeggibili"].iloc[0]
    assert riga["righe"] == 1 and riga["azione"].startswith("righe scartate")
