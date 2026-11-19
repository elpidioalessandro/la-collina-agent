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


def test_confronta_stagioni_cappotti_2024(dati):
    out = analisi.confronta_stagioni(dati, "AI24", categoria="capospalla")
    st = {r["stagione"]: r["sell_through_pct"] for r in out["stagioni"]}
    assert st == pytest.approx({"AI23": 65.94, "AI24": 48.67, "AI25": 69.4}, abs=0.01)
    assert "il più basso" in out["sintesi"] and "17,3 punti sotto AI23" in out["sintesi"]
    assert "ordine è stato troppo alto" in out["sintesi"] and "almeno due" in out["segnalazione"][0]
    with pytest.raises(ValueError, match="PE24"):
        analisi.confronta_stagioni(dati, "2024")


def test_confronti_con_il_negozio_gia_calcolati(dati):
    out = analisi.resi(dati, "brand_motivo")
    riga = {r["brand"]: r for r in out["tabella"]}
    assert out["resi_del_negozio_pct"]["totale"] == pytest.approx(3.03, abs=0.01)
    assert riga["Cruciverba"]["rispetto_al_negozio"] == "sotto"
    assert riga["Lardoni"]["rispetto_al_negozio"] == "sopra"
    assert analisi.sell_through(dati)["tabella"][0]["rispetto_al_negozio"] == "sotto"


def test_sell_through_elenca_i_brand_sotto_soglia_e_spiega_la_regola(dati):
    out = analisi.sell_through(dati)
    assert out["sotto_70_pct"] == ["Lido Club", "FreePlace Outerwear", "Dipartimento 3"]
    assert "almeno due soglie" in out["nota"] and "indicativo" in out["nota"]
    assert "indicativo" not in analisi.sell_through(dati, stagione="AI24")["nota"]


def test_soglie_fornitori_come_la_sez_8_6(dati):
    out = analisi.soglie_fornitori(dati, "AI24")
    assert len(out["da_segnalare"]) == 1 and out["da_segnalare"][0].startswith("Hole in AI24: 2 soglie")
    cappotti = analisi.confronta_stagioni(dati, "AI24", categoria="capospalla")["segnalazione"]
    assert cappotti == [next(b for b in out["brand"] if b.startswith("FreePlace Outerwear"))]
    assert "non va segnalato" in cappotti[0]
    tutte = analisi.soglie_fornitori(dati)["da_segnalare"]
    assert [x.split(":")[0] for x in tutte] == ["Dipartimento 3 in AI23", "Lido Club in AI23", "Hole in AI24", "Hole in PE23"]


def test_resi_per_motivo_di_un_brand_con_totale(dati):
    """Il totale c'è sempre: senza, il modello somma da solo e il controllo finale toglie il numero."""
    r = analisi.resi(dati, raggruppa_per="motivo", brand="Cruciverba")
    assert r["totale_resi"] == sum(riga["resi"] for riga in r["tabella"]) == 51
    assert r["totale_pct_sui_venduti"] == 2.89
    assert r["resi_del_negozio_pct"] == 3.03 and r["rispetto_al_negozio"] == "sotto"


def test_sell_through_dice_chi_va_segnalato_davvero(dati):
    st = analisi.sell_through(dati, "brand")
    assert st["da_segnalare_per_rinegoziare"] == analisi.soglie_fornitori(dati)["da_segnalare"]
    assert "soltanto sotto il 70%" in st["nota"]
    segnalati = " ".join(st["da_segnalare_per_rinegoziare"])
    assert "FreePlace" not in segnalati  # sotto il 70% ma con una sola soglia


def test_resi_di_un_brand_con_la_sua_posizione(dati):
    """Il confronto con gli altri brand arriva calcolato: «il più basso» il modello non lo può inventare."""
    cruciverba = analisi.resi(dati, raggruppa_per="motivo", brand="Cruciverba")["posizione_tra_i_brand"]
    assert cruciverba == ("4° su 10 brand per tasso di resi (1° = più resi): non è né il più alto "
                          "(Lardoni, 4,73%) né il più basso (Lieve, 0,50%).")
    lardoni = analisi.resi(dati, raggruppa_per="brand_motivo", brand="Lardoni")["posizione_tra_i_brand"]
    assert lardoni.startswith("1° su 10") and lardoni.endswith("è il più alto del negozio.")
    assert "posizione_tra_i_brand" not in analisi.resi(dati, raggruppa_per="brand")
