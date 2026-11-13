import pandas as pd

from calendario import info_saldi, periodi_saldi
from pulizia import pulisci

RAGGRUPPAMENTI = ["nessuno", "anno", "mese", "stagione", "brand", "categoria", "motivo"]
TETTO_CLIENTE_ABITUALE = 10
GIORNI_RESO = 14
VALIDITA_BUONO = 180


class Dati:
    """Dati puliti di vendite e ordini, con le colonne derivate usate dalle analisi."""

    def __init__(self, vendite_grezze: pd.DataFrame, ordini_grezzi: pd.DataFrame):
        self.righe_grezze = {"vendite": len(vendite_grezze), "ordini": len(ordini_grezzi)}
        self.v, self.o, self.resoconto = pulisci(vendite_grezze, ordini_grezzi)
        self.saldi = periodi_saldi(self.v["data_ora"].dt.year.min(), self.v["data_ora"].dt.year.max())
        self.v = self.v.join(info_saldi(self.v["data_ora"], self.saldi))
        self.v["anno"] = self.v["data_ora"].dt.year
        self.v["mese"] = self.v["data_ora"].dt.to_period("M").astype(str)
        self.costo = self.o.groupby("articolo")["costo_unitario"].agg(lambda s: s.mode()[0])

    @classmethod
    def da_csv(cls, vendite_csv, ordini_csv):
        return cls(pd.read_csv(vendite_csv), pd.read_csv(ordini_csv))

    @property
    def vendite(self):
        return self.v[self.v["tipo_movimento"] == "vendita"]

    @property
    def resi(self):
        return self.v[self.v["tipo_movimento"] == "reso"]


def _valori(df, col):
    return sorted(df[col].dropna().astype(str).unique().tolist())


def _filtra(df, data_inizio=None, data_fine=None, brand=None, categoria=None, stagione=None,
            col_data="data_ora"):
    """Applica i filtri; se il risultato è vuoto solleva un errore con i valori disponibili."""
    out = df
    if data_inizio:
        out = out[out[col_data] >= pd.Timestamp(data_inizio)]
    if data_fine:
        out = out[out[col_data] < pd.Timestamp(data_fine) + pd.Timedelta(days=1)]
    for col, val in [("brand", brand), ("categoria", categoria), ("stagione", stagione)]:
        if val:
            scelta = out[out[col].str.lower() == str(val).lower()]
            if scelta.empty:
                raise ValueError(f"Nessun dato per {col} = '{val}'. Valori disponibili: {_valori(df, col)}.")
            out = scelta
    if out.empty:
        raise ValueError(f"Nessun dato nel periodo {data_inizio} - {data_fine}. Dati disponibili dal "
                         f"{df[col_data].min():%Y-%m-%d} al {df[col_data].max():%Y-%m-%d}.")
    return out


def _chiave(raggruppa_per):
    if raggruppa_per not in RAGGRUPPAMENTI:
        raise ValueError(f"raggruppa_per deve essere uno tra {RAGGRUPPAMENTI}.")
    return None if raggruppa_per == "nessuno" else raggruppa_per


def _tabella(df: pd.DataFrame) -> list:
    return df.reset_index().round(2).to_dict(orient="records")


def info_dati(d: Dati) -> dict:
    v = d.v
    return {
        "periodo_vendite": f"{v['data_ora'].min():%Y-%m-%d} / {v['data_ora'].max():%Y-%m-%d}",
        "anni_completi": [int(a) for a, g in v.groupby("anno")["data_ora"]
                          if g.min().month == 1 and g.max().month == 12],
        "righe_vendite": len(v), "righe_ordini": len(d.o),
        "brand": _valori(v, "brand"), "categorie": _valori(v, "categoria"),
        "stagioni": _valori(d.o, "stagione"),
        "saldi": [f"{s.stagione}: {s.inizio:%Y-%m-%d} / {s.fine:%Y-%m-%d}" for s in d.saldi.itertuples()
                  if v["data_ora"].min() <= s.fine and s.inizio <= v["data_ora"].max()],
    }


def incasso(d: Dati, raggruppa_per="nessuno", **filtri) -> dict:
    """Incasso delle vendite (esclusi buoni regalo e resi), pezzi, scontrini e sconto medio."""
    v = _filtra(d.vendite, **filtri)
    k = _chiave(raggruppa_per)
    k = "motivo_sconto" if k == "motivo" else k
    g = v.groupby(k) if k else v.groupby(lambda _: "totale")
    t = pd.DataFrame({
        "incasso_euro": g["prezzo_venduto"].sum(),
        "pezzi": g.size(),
        "scontrini": g["scontrino"].nunique(),
        "listino_euro": g["prezzo_listino"].sum(),
    })
    t["sconto_medio_pct"] = (1 - t["incasso_euro"] / t["listino_euro"]) * 100
    t = t.drop(columns="listino_euro")
    out = {"righe_usate": len(v), "tabella": _tabella(t)}
    if raggruppa_per == "anno":
        completi = info_dati(d)["anni_completi"]
        out["nota"] = f"Anni completi: {completi}. Gli altri anni sono parziali e non si confrontano."
    return out


def sell_through(d: Dati, raggruppa_per="brand", stagione=None, brand=None, categoria=None) -> dict:
    """Pezzi venduti diviso pezzi ricevuti, in totale e a prezzo pieno."""
    k = _chiave(raggruppa_per)
    if k in ("anno", "mese", "motivo"):
        raise ValueError("Il sell-through si calcola per brand, categoria o stagione.")
    v = _filtra(d.vendite, stagione=stagione, brand=brand, categoria=categoria)
    o = _filtra(d.o, stagione=stagione, brand=brand, categoria=categoria, col_data="data_arrivo")
    ricevuti = o.groupby(k)["qta_ricevuta"].sum() if k else pd.Series({"totale": o["qta_ricevuta"].sum()})
    venduti = v.groupby(k).size() if k else pd.Series({"totale": len(v)})
    pieni = v[v["sconto_pct"] == 0]
    pieni = pieni.groupby(k).size() if k else pd.Series({"totale": len(pieni)})
    t = pd.DataFrame({"ricevuti": ricevuti, "venduti": venduti, "venduti_prezzo_pieno": pieni}).fillna(0)
    t["sell_through_pct"] = t["venduti"] / t["ricevuti"] * 100
    t["sell_through_prezzo_pieno_pct"] = t["venduti_prezzo_pieno"] / t["ricevuti"] * 100
    t = t.sort_values("sell_through_pct")
    return {"righe_usate": len(v), "righe_ordini_usate": len(o), "tabella": _tabella(t),
            "nota": "Sell-through = venduti / ricevuti x 100. Soglia di controllo: 70% sul totale della stagione [SEZ 8.6]."}


def resi(d: Dati, raggruppa_per="brand", motivo=None, **filtri) -> dict:
    """Resi per gruppo, in numero e in percentuale sui pezzi venduti dello stesso gruppo.
    raggruppa_per='brand_motivo' dà una tabella brand x motivo, in % sui venduti di ogni brand."""
    r = _filtra(d.resi, **filtri)
    v = _filtra(d.vendite, **filtri)
    if raggruppa_per == "brand_motivo":
        conta = r.groupby(["brand", "motivo_reso"]).size().unstack(fill_value=0)
        t = conta.div(v.groupby("brand").size(), axis=0).fillna(0) * 100
        t["totale"] = t.sum(axis=1)
        t = t.sort_values("totale", ascending=False)
        return {"righe_usate": len(r) + len(v), "valori": "% di resi sui pezzi venduti del brand",
                "tabella": _tabella(t)}
    k = _chiave(raggruppa_per)
    if motivo:
        r = r[r["motivo_reso"] == motivo]
        if r.empty:
            raise ValueError(f"Nessun reso con motivo '{motivo}'. Motivi: {_valori(d.resi, 'motivo_reso')}.")
    if k == "motivo":
        t = r.groupby("motivo_reso").size().to_frame("resi")
        t["pct_sui_venduti"] = t["resi"] / len(v) * 100
    else:
        n = r.groupby(k).size() if k else pd.Series({"totale": len(r)})
        vend = v.groupby(k).size() if k else pd.Series({"totale": len(v)})
        t = pd.DataFrame({"resi": n, "venduti": vend}).fillna(0)
        t["pct_sui_venduti"] = t["resi"] / t["venduti"] * 100
    t = t.sort_values("pct_sui_venduti", ascending=False)
    return {"righe_usate": len(r) + len(v), "motivo": motivo or "tutti", "tabella": _tabella(t)}


def margine(d: Dati, raggruppa_per="brand", **filtri) -> dict:
    """Margine lordo: (incasso - costo dei pezzi venduti) / incasso."""
    k = _chiave(raggruppa_per)
    v = _filtra(d.vendite, **filtri).copy()
    v["costo"] = v["articolo"].map(d.costo)
    senza_costo = int(v["costo"].isna().sum())
    v = v[v["costo"].notna()]
    g = v.groupby(k) if k else v.groupby(lambda _: "totale")
    t = pd.DataFrame({"incasso_euro": g["prezzo_venduto"].sum(), "costo_euro": g["costo"].sum()})
    t["margine_euro"] = t["incasso_euro"] - t["costo_euro"]
    t["margine_pct"] = t["margine_euro"] / t["incasso_euro"] * 100
    t = t.sort_values("margine_pct")
    return {"righe_usate": len(v), "righe_escluse_senza_costo": senza_costo, "tabella": _tabella(t)}


def sconti(d: Dati, raggruppa_per="motivo", **filtri) -> dict:
    """Euro concessi in sconti (listino - venduto), per motivo o altro gruppo."""
    k = _chiave(raggruppa_per)
    v = _filtra(d.vendite, **filtri).copy()
    v["sconto_euro"] = v["prezzo_listino"] - v["prezzo_venduto"]
    col = "motivo_sconto" if k == "motivo" else k
    g = v.groupby(col) if col else v.groupby(lambda _: "totale")
    t = pd.DataFrame({"sconto_euro": g["sconto_euro"].sum(), "pezzi": g.size(),
                      "listino_euro": g["prezzo_listino"].sum()})
    t["sconto_pct_sul_listino"] = t["sconto_euro"] / t["listino_euro"] * 100
    t = t.drop(columns="listino_euro").sort_values("sconto_euro", ascending=False)
    return {"righe_usate": len(v), "tabella": _tabella(t)}


def _esempi(df, colonne, n=2):
    return df[colonne].head(n).astype(str).to_dict(orient="records")


def controlli(d: Dati) -> dict:
    """Violazioni delle regole del manuale (Parte 10): conteggio, sezione violata ed esempi."""
    v, vend, resi_ = d.v, d.vendite, d.resi
    base = ["data_ora", "scontrino", "brand", "categoria", "prezzo_listino", "prezzo_venduto", "sconto_pct",
            "motivo_sconto"]
    trovati = []

    def aggiungi(nome, sezione, righe, colonne=base):
        trovati.append({"controllo": nome, "regola": sezione, "casi": int(len(righe)),
                        "esempi": _esempi(righe, colonne)})

    minuti = vend["data_ora"].dt.hour * 60 + vend["data_ora"].dt.minute
    lunedi = (vend["data_ora"].dt.day_of_week == 0) & (minuti < 16 * 60 + 30)
    aggiungi("vendita il lunedì mattina, a negozio chiuso", "[SEZ 1.2]", vend[lunedi])
    fuori = ~lunedi & ((minuti < 600) | ((minuti >= 780) & (minuti < 990)) | (minuti >= 1200))
    aggiungi("vendita fuori dagli orari di apertura", "[SEZ 1.2]", vend[fuori])

    abituale = vend["motivo_sconto"] == "cliente_abituale"
    aggiungi("sconto al cliente abituale oltre il 10%", "[SEZ 4.1]",
             vend[abituale & (vend["sconto_pct"] > TETTO_CLIENTE_ABITUALE)])
    cambio = vend["metodo_pagamento"] == "cambio"
    aggiungi("sconto al cliente abituale su un capo in saldo", "[SEZ 4.2]",
             vend[abituale & ~cambio & vend["stagione_in_saldo"].eq(vend["stagione"])
                  & (vend["categoria"] != "profumo")])

    saldo = vend["motivo_sconto"] == "saldo"
    aggiungi("saldo nei 30 giorni di divieto prima dei saldi", "[SEZ 4.4]", vend[saldo & vend["divieto_promo"]])
    aggiungi("saldo fuori dalle date dei saldi", "[SEZ 4.3]",
             vend[saldo & vend["stagione_in_saldo"].isna() & ~vend["divieto_promo"]])
    dentro = saldo & vend["stagione_in_saldo"].notna()
    aggiungi("capo in saldo che non è della stagione in saldo", "[SEZ 4.5]",
             vend[dentro & (vend["stagione"] != vend["stagione_in_saldo"])])
    aggiungi("sconto di saldo diverso dallo scaglione della settimana", "[SEZ 4.5]",
             vend[dentro & ~cambio & (vend["stagione"] == vend["stagione_in_saldo"])
                  & (vend["sconto_pct"] != vend["sconto_scaglione"])])
    aggiungi("profumo venduto in saldo", "[SEZ 4.6]", vend[saldo & (vend["categoria"] == "profumo")])

    originale = v.set_index("id_riga")["data_ora"]
    giorni = (resi_["data_ora"] - resi_["rif_vendita"].map(originale)).dt.days
    col_resi = ["data_ora", "scontrino", "brand", "categoria", "motivo_reso", "esito_reso"]
    aggiungi("reso accettato oltre 14 giorni", "[SEZ 5.3]", resi_[giorni > GIORNI_RESO], col_resi)
    non_cambiabili = resi_["categoria"].isin(["costume", "profumo"]) & (resi_["motivo_reso"] != "difetto")
    aggiungi("costume o profumo reso senza difetto", "[SEZ 5.6]", resi_[non_cambiabili], col_resi)
    difetti = resi_[(resi_["motivo_reso"] == "difetto") & (resi_["reso_fornitore"] == "no")].copy()
    aggiungi("reso per difetto non rimandato al fornitore", "[SEZ 6.3]", difetti, col_resi)

    emessi = v[v["tipo_movimento"].isin(["reso", "buono_regalo"]) & v["id_buono"].notna()]
    emissione = emessi.groupby("id_buono")["data_ora"].min()
    usati = vend[(vend["metodo_pagamento"] == "buono") & vend["id_buono"].notna()]
    eta = (usati["data_ora"] - usati["id_buono"].map(emissione)).dt.days
    aggiungi("buono accettato oltre 180 giorni", "[SEZ 5.7] [SEZ 5.8]", usati[eta > VALIDITA_BUONO],
             ["data_ora", "scontrino", "id_buono", "prezzo_venduto"])

    incomplete = d.o[d.o["qta_ricevuta"] < d.o["qta_ordinata"]]
    trovati.append({"controllo": "consegna incompleta (ricevuti meno degli ordinati)", "regola": "[SEZ 8.4] [SEZ 8.5]",
                    "casi": int(len(incomplete)),
                    "per_brand": incomplete.groupby("brand").size().to_dict(),
                    "esempi": _esempi(incomplete, ["brand", "articolo", "taglia", "qta_ordinata", "qta_ricevuta"])})

    trovati.append({"controllo": "credito perso per difetti non rimandati (euro al costo)", "regola": "[SEZ 6.3]",
                    "casi": int(len(difetti)),
                    "euro": round(float(difetti["articolo"].map(d.costo).sum()), 2), "esempi": []})

    violazioni = [t for t in trovati if t["casi"] > 0]
    return {"righe_usate": len(v),
            "riepilogo": [f"{t['controllo']}: {t['casi']} casi {t['regola']}" for t in violazioni],
            "controlli_senza_violazioni": [t["controllo"] for t in trovati if t["casi"] == 0],
            "violazioni": violazioni,
            "nota": "Una violazione è un fatto da verificare, non una colpa [SEZ 10.1]."}


def resoconto_pulizia(d: Dati) -> dict:
    return {"righe_grezze": d.righe_grezze,
            "righe_pulite": {"vendite": len(d.v), "ordini": len(d.o)},
            "correzioni": d.resoconto.to_dict(orient="records")}


def nota_dati(d: Dati) -> str:
    """Riga sintetica sulla qualità dei dati, da mostrare sotto ogni risposta."""
    r = d.resoconto
    scartate = int(r.loc[r["azione"] == "eliminate", "righe"].sum())
    corrette = int(r.loc[r["azione"] != "eliminate", "righe"].sum())
    return (f"Dati: {d.righe_grezze['vendite']} righe di vendite e {d.righe_grezze['ordini']} di ordini; "
            f"{scartate} righe duplicate scartate, {corrette} valori corretti in pulizia.")
