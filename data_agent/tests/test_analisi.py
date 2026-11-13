import pytest

import analisi


def _per(tabella, chiave, colonna):
    return {r[chiave]: r[colonna] for r in tabella}


def test_incasso_per_anno(dati):
    out = analisi.incasso(dati, "anno")
    inc = _per(out["tabella"], "anno", "incasso_euro")
    assert round(inc[2024]) == 544005 and round(inc[2025]) == 606128
    assert "2024, 2025" in out["nota"]


def test_sell_through_piu_basso(dati):
    t = analisi.sell_through(dati)["tabella"]
    assert t[0]["brand"] == "Lido Club" and t[0]["sell_through_pct"] == pytest.approx(56.22, abs=0.01)
    assert t[-1]["brand"] == "Ago&Filo"


def test_resi_per_taglia_e_difetto(dati):
    taglia = analisi.resi(dati, "brand", motivo="taglia")["tabella"]
    assert [r["brand"] for r in taglia[:2]] == ["Lardoni", "Cruciverba"]
    difetto = analisi.resi(dati, "brand", motivo="difetto")["tabella"]
    assert difetto[0]["brand"] == "Dipartimento 3" and difetto[0]["pct_sui_venduti"] == pytest.approx(1.22, abs=0.01)


def test_controlli_trovano_le_anomalie_piantate(dati):
    casi = {v["controllo"]: v["casi"] for v in analisi.controlli(dati)["violazioni"]}
    assert casi["sconto al cliente abituale oltre il 10%"] == 12
    assert casi["saldo nei 30 giorni di divieto prima dei saldi"] == 15
    assert casi["profumo venduto in saldo"] == 5
    assert casi["vendita il lunedì mattina, a negozio chiuso"] == 6
    assert "sconto di saldo diverso dallo scaglione della settimana" not in casi


def test_filtro_sbagliato_dice_cosa_esiste(dati):
    with pytest.raises(ValueError, match="Valori disponibili"):
        analisi.incasso(dati, brand="Gucci")
    with pytest.raises(ValueError, match="Dati disponibili dal"):
        analisi.incasso(dati, data_inizio="2030-01-01")


def test_margine_esclude_righe_senza_costo(dati):
    out = analisi.margine(dati)
    assert out["righe_escluse_senza_costo"] == 1
    assert min(r["margine_pct"] for r in out["tabella"]) > 0


def test_resi_brand_per_motivo(dati):
    t = analisi.resi(dati, "brand_motivo")["tabella"]
    lardoni = next(r for r in t if r["brand"] == "Lardoni")
    assert lardoni["taglia"] == pytest.approx(3.29, abs=0.01)
    assert t[0]["brand"] == "Lardoni"
