import re

import pandas as pd

from caricamento import leggi_ordini, leggi_vendite
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
        """Legge e pulisce i due CSV. Un file mancante o malformato solleva ErroreDati con un messaggio chiaro."""
        return cls(leggi_vendite(vendite_csv), leggi_ordini(ordini_csv))

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


def _rispetto(valore, riferimento) -> str:
    if valore > riferimento + 0.005:
        return "sopra"
    if valore < riferimento - 0.005:
        return "sotto"
    return "in linea"


def _con_riferimento(t: pd.DataFrame, colonna: str, riferimento: float) -> pd.DataFrame:
    """Aggiunge a ogni riga se il valore è sopra o sotto il dato complessivo del negozio."""
    t = t.copy()
    t["rispetto_al_negozio"] = [_rispetto(x, riferimento) for x in t[colonna]]
    return t


def _it(x: float, decimali=1) -> str:
    return f"{x:,.{decimali}f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


SOGLIE_SELL_THROUGH = ("Per il manuale [SEZ 8.6]: almeno l'80% = sta andando bene; sotto il 70% = l'ordine è stato "
                       "troppo alto e la merce che resta va all'outlet. La segnalazione al titolare per rinegoziazione "
                       "richiede almeno due soglie di controllo superate nella stessa stagione: il sell-through sotto il 70% "
                       "da solo non basta.")


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
    out = {"righe_usate": len(v), "righe_ordini_usate": len(o)}
    if k:
        negozio = len(v) / o["qta_ricevuta"].sum() * 100
        t = _con_riferimento(t, "sell_through_pct", negozio)
        out["sell_through_del_negozio_pct"] = round(negozio, 2)
        nomi = t.index.astype(str)
        out["sotto_70_pct"] = [n for n, x in zip(nomi, t["sell_through_pct"]) if x < 70]
        out["almeno_80_pct"] = [n for n, x in zip(nomi, t["sell_through_pct"]) if x >= 80]
        # Chi va davvero segnalato per rinegoziare: calcolato con le quattro soglie, non con il solo sell-through.
        try:
            out["da_segnalare_per_rinegoziare"] = soglie_fornitori(d, stagione)["da_segnalare"]
        except ValueError:
            pass  # stagione senza ordini: il sell-through resta, la segnalazione non si può calcolare
    out["tabella"] = _tabella(t)
    nota = "Sell-through = venduti / ricevuti x 100, saldi compresi. " + SOGLIE_SELL_THROUGH
    if k:
        nota += (" I brand da segnalare per rinegoziare sono solo quelli in da_segnalare_per_rinegoziare: per un "
                 "brand che è soltanto sotto il 70% il manuale prevede l'outlet per la merce che resta, non la segnalazione.")
    if not stagione and k != "stagione":
        nota += " Le soglie valgono per una stagione: qui le stagioni sono sommate, quindi il confronto è indicativo."
    out["nota"] = nota
    return out


def _soglie_stagione(d: Dati, stagione: str) -> list:
    """Le quattro soglie di controllo dei fornitori [SEZ 8.6], brand per brand, in una stagione."""
    v = d.vendite[d.vendite["stagione"] == stagione]
    o = d.o[d.o["stagione"] == stagione]
    r = d.resi[d.resi["stagione"] == stagione]
    venduti = v.groupby("brand").size()
    ricevuti = o.groupby("brand")["qta_ricevuta"].sum()
    difetti = r[r["motivo_reso"] == "difetto"].groupby("brand").size()
    incomplete = o[o["qta_ricevuta"] < o["qta_ordinata"]].groupby("brand").size()
    sconto = v[v["stagione_in_saldo"].isna()].groupby("brand")["sconto_pct"].mean()
    fine_saldi = d.saldi.loc[d.saldi["stagione"] == stagione, "fine"]
    conclusa = bool(len(fine_saldi) and fine_saldi.iloc[0] <= d.v["data_ora"].max())
    righe = []
    for brand in sorted(ricevuti.index):
        vend = int(venduti.get(brand, 0))
        st = vend / ricevuti[brand] * 100 if ricevuti[brand] else 0.0
        dif = difetti.get(brand, 0) / vend * 100 if vend else 0.0
        inc = int(incomplete.get(brand, 0))
        sc = float(sconto.get(brand, 0.0))
        superate = []
        if dif > 1:
            superate.append(f"resi per difetto al {_it(dif, 2)}% dei venduti (soglia 1%)")
        if st < 70 and conclusa:
            superate.append(f"sell-through al {_it(st)}% (soglia 70%)")
        if inc:
            superate.append(f"{inc} consegne incomplete")
        if sc > 10:
            superate.append(f"sconto medio fuori dai saldi al {_it(sc)}% (soglia 10%)")
        righe.append({"stagione": stagione, "brand": brand, "sell_through_pct": round(st, 2),
                      "resi_difetto_pct": round(dif, 2), "consegne_incomplete": inc,
                      "sconto_medio_fuori_saldi_pct": round(sc, 2), "soglie_superate": superate,
                      "da_segnalare": len(superate) >= 2})
    return righe


def _esito_soglie(r: dict) -> str:
    n = len(r["soglie_superate"])
    if n == 0:
        return f"{r['brand']} in {r['stagione']}: nessuna soglia superata, non va segnalato [SEZ 8.6]."
    elenco = "; ".join(r["soglie_superate"])
    if n == 1:
        return (f"{r['brand']} in {r['stagione']}: una sola soglia superata ({elenco}), quindi non va segnalato "
                f"per rinegoziazione: ne servono almeno due nella stessa stagione [SEZ 8.6].")
    return f"{r['brand']} in {r['stagione']}: {n} soglie superate ({elenco}), va segnalato al titolare per rinegoziazione [SEZ 8.6]."


def soglie_fornitori(d: Dati, stagione=None) -> dict:
    """Brand che superano le soglie di controllo dei fornitori e vanno segnalati per rinegoziazione."""
    stagioni = [str(stagione).strip().upper()] if stagione else _valori(d.o, "stagione")
    for s in stagioni:
        if s not in set(_valori(d.o, "stagione")):
            raise ValueError(f"Nessun dato per la stagione {s}. Stagioni disponibili: {_valori(d.o, 'stagione')}.")
    righe = [r for s in stagioni for r in _soglie_stagione(d, s)]
    segnalare = [_esito_soglie(r) for r in righe if r["da_segnalare"]]
    out = {"righe_usate": len(righe),
           "da_segnalare": segnalare or ["Nessun brand supera almeno due soglie nella stessa stagione."],
           "regola": "Un brand va segnalato al titolare per rinegoziazione quando supera almeno due di queste soglie "
                     "nella stessa stagione: resi per difetto oltre l'1% dei venduti, sell-through sotto il 70% dei "
                     "ricevuti, consegne incomplete, sconto medio fuori dai saldi oltre il 10% [SEZ 8.6]."}
    if stagione:
        out["brand"] = [_esito_soglie(r) for r in righe]
    else:
        out["con_una_soglia"] = [_esito_soglie(r) for r in righe if len(r["soglie_superate"]) == 1]
    return out


def _stagioni_vicine(d: Dati, stagione: str) -> list:
    m = re.fullmatch(r"(PE|AI)(\d{2})", str(stagione).strip().upper())
    if not m:
        raise ValueError("La stagione va scritta come PE24 (primavera-estate 2024) o AI24 (autunno-inverno 2024).")
    tipo, anno = m.group(1), int(m.group(2))
    disponibili = set(_valori(d.o, "stagione"))
    if f"{tipo}{anno:02d}" not in disponibili:
        raise ValueError(f"Nessun dato per la stagione {tipo}{anno:02d}. Stagioni disponibili: {sorted(disponibili)}.")
    return [s for s in (f"{tipo}{anno - 1:02d}", f"{tipo}{anno:02d}", f"{tipo}{anno + 1:02d}") if s in disponibili]


def confronta_stagioni(d: Dati, stagione: str, brand=None, categoria=None) -> dict:
    """Sell-through e incasso di una stagione confrontati con la stessa stagione dell'anno prima e dopo."""
    stagione = str(stagione).strip().upper()
    righe = []
    for s in _stagioni_vicine(d, stagione):
        try:
            st = sell_through(d, "nessuno", stagione=s, brand=brand, categoria=categoria)["tabella"][0]
        except ValueError:
            continue
        v = _filtra(d.vendite, stagione=s, brand=brand, categoria=categoria)
        fine_saldi = d.saldi.loc[d.saldi["stagione"] == s, "fine"]
        righe.append({"stagione": s, "ricevuti": int(st["ricevuti"]), "venduti": int(st["venduti"]),
                      "sell_through_pct": st["sell_through_pct"],
                      "sell_through_prezzo_pieno_pct": st["sell_through_prezzo_pieno_pct"],
                      "incasso_euro": round(float(v["prezzo_venduto"].sum()), 2),
                      "stagione_conclusa": bool(len(fine_saldi) and fine_saldi.iloc[0] <= d.v["data_ora"].max())})
    if not any(r["stagione"] == stagione for r in righe):
        raise ValueError(f"Nessun dato per la stagione {stagione} con questi filtri.")
    chi = " ".join(x for x in (f"dei {categoria}" if categoria else "", f"di {brand}" if brand else "") if x)
    chi = chi or "del negozio"
    target = next(r for r in righe if r["stagione"] == stagione)
    altre = [r for r in righe if r is not target]
    frasi = []
    for r in altre:
        diff = target["sell_through_pct"] - r["sell_through_pct"]
        frasi.append(f"{_it(abs(diff))} punti {'sopra' if diff > 0 else 'sotto'} {r['stagione']} ({_it(r['sell_through_pct'])}%)")
    valori = [r["sell_through_pct"] for r in righe]
    posizione = ("il più basso" if target["sell_through_pct"] == min(valori)
                 else "il più alto" if target["sell_through_pct"] == max(valori) else "intermedio")
    sintesi = (f"Sell-through {chi} in {stagione}: {_it(target['sell_through_pct'])}% "
               f"({target['venduti']} venduti su {target['ricevuti']} ricevuti)")
    if altre:
        sintesi += f", {posizione} tra {', '.join(r['stagione'] for r in righe)}: " + " e ".join(frasi)
    st = target["sell_through_pct"]
    if st < 70:
        sintesi += ". Sotto il 70%: per il manuale l'ordine è stato troppo alto e la merce che resta va all'outlet [SEZ 8.6]."
    elif st >= 80:
        sintesi += ". Almeno l'80%: per il manuale vuol dire che sta andando bene [SEZ 8.6]."
    else:
        sintesi += ". Tra il 70% e l'80%."
    sintesi += f" Incasso dei capi {stagione}: {_it(target['incasso_euro'], 2)} €"
    confronti = []
    for r in altre:
        diff = target["incasso_euro"] - r["incasso_euro"]
        confronti.append(f"{_it(abs(diff), 2)} € in {'più' if diff > 0 else 'meno'} di {r['stagione']} "
                         f"({_it(r['incasso_euro'], 2)} €)")
    if confronti:
        sintesi += ", " + " e ".join(confronti)
    sintesi += "."
    v_target = _filtra(d.vendite, stagione=stagione, brand=brand, categoria=categoria)
    brand_target = set(v_target["brand"]) | ({brand} if brand else set())
    segnalazione = [_esito_soglie(r) for r in _soglie_stagione(d, stagione) if r["brand"] in brand_target]
    return {"righe_usate": int(sum(r["venduti"] for r in righe)), "sintesi": sintesi, "stagioni": righe,
            "segnalazione": segnalazione,
            "nota": "Stagione = collezione del capo (AI24 = autunno-inverno 2024, venduta da settembre 2024 ai saldi "
                    "di febbraio 2025), non l'anno solare. L'incasso è quello dei capi della stagione."}


def _posizione_resi(d: Dati, brand: str, motivo=None, **filtri) -> str | None:
    """«4° su 10 brand per tasso di resi»: il confronto vero, perché il modello non lo inventi."""
    classifica = resi(d, "brand", motivo=motivo, **filtri)["tabella"]
    nomi = [r["brand"] for r in classifica]
    if brand not in nomi:
        return None
    pos, primo, ultimo = nomi.index(brand) + 1, classifica[0], classifica[-1]
    testo = f"{pos}° su {len(nomi)} brand per tasso di resi{f' per {motivo}' if motivo else ''} (1° = più resi)"
    if pos == 1:
        return testo + ": è il più alto del negozio."
    if pos == len(nomi):
        return testo + ": è il più basso del negozio."
    return (testo + f": non è né il più alto ({primo['brand']}, {_it(primo['pct_sui_venduti'], 2)}%) "
            f"né il più basso ({ultimo['brand']}, {_it(ultimo['pct_sui_venduti'], 2)}%).")


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
        negozio = (r.groupby("motivo_reso").size() / len(v) * 100).round(2).to_dict()
        negozio["totale"] = round(len(r) / len(v) * 100, 2)
        t = _con_riferimento(t, "totale", negozio["totale"])
        extra = {}
        if filtri.get("brand"):
            altri = {c: x for c, x in filtri.items() if c != "brand"}
            posizione = _posizione_resi(d, filtri["brand"], **altri)
            if posizione:
                extra["posizione_tra_i_brand"] = posizione
        return {"righe_usate": len(r) + len(v), "valori": "% di resi sui pezzi venduti del brand", **extra,
                "resi_del_negozio_pct": negozio,
                "nota": "rispetto_al_negozio confronta il totale del brand con il totale del negozio.",
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
    out = {"righe_usate": len(r) + len(v), "motivo": motivo or "tutti"}
    if k and k != "motivo":
        negozio = len(r) / len(v) * 100
        t = _con_riferimento(t, "pct_sui_venduti", negozio)
        out["resi_del_negozio_pct"] = round(negozio, 2)
    if k == "motivo":
        # Il totale serve sempre: senza, il modello somma da solo e il controllo finale toglie il numero.
        out["totale_resi"] = len(r)
        out["totale_pct_sui_venduti"] = round(len(r) / len(v) * 100, 2) if len(v) else 0.0
        if filtri:
            negozio = len(d.resi) / len(d.vendite) * 100
            out["resi_del_negozio_pct"] = round(negozio, 2)
            out["rispetto_al_negozio"] = _rispetto(out["totale_pct_sui_venduti"], round(negozio, 2))
    if filtri.get("brand") and k != "brand":
        altri = {c: x for c, x in filtri.items() if c != "brand"}
        posizione = _posizione_resi(d, filtri["brand"], motivo=motivo, **altri)
        if posizione:
            out["posizione_tra_i_brand"] = posizione
    out["tabella"] = _tabella(t)
    return out


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
    out = {"righe_usate": len(v), "righe_escluse_senza_costo": senza_costo}
    if k:
        negozio = (1 - v["costo"].sum() / v["prezzo_venduto"].sum()) * 100
        t = _con_riferimento(t, "margine_pct", negozio)
        out["margine_del_negozio_pct"] = round(negozio, 2)
    out["tabella"] = _tabella(t)
    return out


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
            "riepilogo": [f"{t['controllo']}: {_it(t['euro'], 2)} € ({t['casi']} resi) {t['regola']}" if "euro" in t
                          else f"{t['controllo']}: {t['casi']} casi {t['regola']}" for t in violazioni],
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
