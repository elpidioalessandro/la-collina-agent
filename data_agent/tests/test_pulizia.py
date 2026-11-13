import pandas as pd
import pytest

import config
from pulizia import pulisci

RIFERIMENTO = config.ROOT_DIR / "valutazione"


def test_resoconto_e_righe(dati):
    assert len(dati.v) == 16405 and len(dati.o) == 4511
    r = dati.resoconto.set_index(["file", "regola", "azione"])["righe"]
    assert r[("vendite", "righe duplicate", "eliminate")] == 164
    assert r[("ordini", "righe duplicate", "eliminate")] == 3
    assert dati.v["data_ora"].dtype.kind == "M" and dati.v["prezzo_venduto"].dtype.kind == "f"


@pytest.mark.skipif(not (RIFERIMENTO / "vendite_riferimento.csv").exists(), reason="dati di riferimento assenti")
def test_uguale_al_riferimento(dati):
    rif = pd.read_csv(RIFERIMENTO / "vendite_riferimento.csv", parse_dates=["data_ora"]).set_index("id_riga")
    v = dati.v.set_index("id_riga").loc[rif.index]
    diverse = {}
    for col in rif.columns:
        uguali = (v[col] == rif[col]) | (v[col].isna() & rif[col].isna())
        if v[col].dtype.kind == "f":
            uguali |= (v[col] - rif[col]).abs() < 0.011
        diverse[col] = int((~uguali).sum())
    assert {k: n for k, n in diverse.items() if n} == {"articolo": 1}


def test_motivo_non_deducibile_fuori_saldi():
    righe = pd.DataFrame({
        "id_riga": [1, 2], "data_ora": ["2024-03-10 11:00:00", "2024-01-10 11:00:00"],
        "scontrino": ["S2024-000001", "S2024-000002"], "articolo": ["A", "A"], "brand": ["Lardoni"] * 2,
        "categoria": ["giacca"] * 2, "taglia": ["50"] * 2, "colore": ["blu"] * 2, "stagione": ["AI23"] * 2,
        "prezzo_listino": [100.0, 100.0], "prezzo_venduto": ["80", "70"], "sconto_pct": [20, 30],
        "motivo_sconto": [None, None], "tipo_movimento": ["vendita"] * 2,
    })
    ordini = pd.DataFrame({"id_ordine": [1], "articolo": ["A"], "taglia": ["50"], "brand": ["Lardoni"],
                           "categoria": ["giacca"], "colore": ["blu"], "stagione": ["AI23"],
                           "data_ordine": ["2023-02-20"], "data_arrivo": ["2023-08-10"], "qta_ordinata": [2],
                           "qta_ricevuta": [2], "costo_unitario": [40.0], "prezzo_listino": [100.0]})
    v, _, _ = pulisci(righe, ordini)
    assert pd.isna(v.loc[0, "motivo_sconto"]) and v.loc[1, "motivo_sconto"] == "saldo"
