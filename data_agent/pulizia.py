import pandas as pd

from calendario import info_saldi, periodi_saldi

INIZIO, FINE = pd.Timestamp("2023-03-02"), pd.Timestamp("2026-03-02")
NOMI_TAGLIE = {"SMALL": "S", "MEDIUM": "M", "LARGE": "L", "EXTRA LARGE": "XL"}
COLORI_SINONIMI = {"blu navy": "blu"}


def forma_canonica(colonna):
    pulita = colonna.str.strip()
    chiave = pulita.str.lower()
    canonica = pulita.groupby(chiave).agg(lambda s: s.value_counts().index[0])
    return chiave.map(canonica)


def pulisci_vendite(vendite):
    v = vendite.copy()
    resoconto = []

    def nota(regola, righe, azione):
        resoconto.append({"file": "vendite", "regola": regola, "righe": int(righe), "azione": azione})

    n = len(v)
    v = v.drop_duplicates()
    nota("righe duplicate", n - len(v), "eliminate")

    italiane = v["data_ora"].str.contains("/")
    iso = pd.to_datetime(v["data_ora"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    ita = pd.to_datetime(v["data_ora"], format="%d/%m/%Y %H:%M", errors="coerce")
    v["data_ora"] = iso.fillna(ita)
    nota("date in formato italiano", italiane.sum(), "convertite")

    illeggibili = v["data_ora"].isna()
    v = v[~illeggibili].copy()
    nota("date illeggibili", illeggibili.sum(), "righe scartate: senza data non si sa a che periodo appartengono")

    fuori = (v["data_ora"] < INIZIO) | (v["data_ora"] >= FINE)
    anno = v.loc[fuori, "scontrino"].str[1:5].astype(int)
    if fuori.any():
        v.loc[fuori, "data_ora"] = [d.replace(year=a) for d, a in zip(v.loc[fuori, "data_ora"], anno)]
    nota("date fuori periodo", fuori.sum(), "anno corretto con quello dello scontrino")

    prima = v["taglia"].copy()
    t = v["taglia"].str.strip().str.upper().str.removeprefix("TG ")
    v["taglia"] = t.replace(NOMI_TAGLIE)
    nota("taglie scritte in modo diverso", (prima.notna() & (prima != v["taglia"])).sum(), "uniformate")

    prima = v["brand"].copy()
    v["brand"] = forma_canonica(v["brand"])
    nota("brand scritti in modo diverso", (prima.notna() & (prima != v["brand"])).sum(), "uniformati")

    prima = v["colore"].copy()
    v["colore"] = v["colore"].str.strip().str.lower().replace(COLORI_SINONIMI)
    nota("colori scritti in modo diverso", (prima.notna() & (prima != v["colore"])).sum(), "uniformati")

    virgola = v["prezzo_venduto"].str.contains(",", na=False)
    v["prezzo_venduto"] = pd.to_numeric(v["prezzo_venduto"].str.replace(",", "."))
    nota("prezzi con la virgola", virgola.sum(), "convertiti in numero")

    negativi = v["prezzo_venduto"] < 0
    v.loc[negativi, "prezzo_venduto"] = -v.loc[negativi, "prezzo_venduto"]
    nota("prezzi negativi", negativi.sum(), "segno corretto")

    fuori_range = ~v["sconto_pct"].between(0, 100)
    calcolato = ((1 - v["prezzo_venduto"] / v["prezzo_listino"]) * 100).round()
    sbagliato = calcolato.notna() & ((calcolato - v["sconto_pct"]).abs() > 1)
    v.loc[sbagliato, "sconto_pct"] = calcolato[sbagliato].astype(int)
    nota("sconti fuori da 0-100", (fuori_range & sbagliato).sum(), "ricalcolati dai prezzi")
    nota("sconti che non tornano con i prezzi", (~fuori_range & sbagliato).sum(), "ricalcolati dai prezzi")

    mancante = v["prezzo_venduto"].isna()
    v.loc[mancante, "prezzo_venduto"] = (v.loc[mancante, "prezzo_listino"]
                                         * (1 - v.loc[mancante, "sconto_pct"] / 100)).round(2)
    nota("prezzi mancanti", mancante.sum(), "ricostruiti da listino e sconto")

    mancante = v["motivo_sconto"].isna()
    saldi = periodi_saldi(v["data_ora"].dt.year.min(), v["data_ora"].dt.year.max())
    in_saldo = info_saldi(v["data_ora"], saldi)["stagione_in_saldo"].notna()
    sconto = v["sconto_pct"]
    dedotto = pd.Series(pd.NA, index=v.index, dtype="object")
    dedotto[sconto == 0] = "nessuno"
    dedotto[(sconto > 0) & (sconto <= 10)] = "cliente_abituale"
    dedotto[(sconto > 10) & in_saldo] = "saldo"
    v.loc[mancante, "motivo_sconto"] = dedotto[mancante]
    non_dedotto = mancante & v["motivo_sconto"].isna()
    nota("motivo dello sconto mancante", (mancante & ~non_dedotto).sum(), "dedotto da sconto e data")
    nota("motivo dello sconto mancante", non_dedotto.sum(), "non deducibile: sconto oltre il 10% fuori dai saldi, riga tenuta e segnalata")

    return v.reset_index(drop=True), resoconto


def pulisci_ordini(ordini, listino_vendite):
    o = ordini.copy()
    resoconto = []

    def nota(regola, righe, azione):
        resoconto.append({"file": "ordini", "regola": regola, "righe": int(righe), "azione": azione})

    n = len(o)
    o = o.drop_duplicates()
    nota("righe duplicate", n - len(o), "eliminate")

    o["data_ordine"] = pd.to_datetime(o["data_ordine"])
    o["data_arrivo"] = pd.to_datetime(o["data_arrivo"])
    invertite = o["data_arrivo"] < o["data_ordine"]
    o.loc[invertite, ["data_ordine", "data_arrivo"]] = o.loc[invertite, ["data_arrivo", "data_ordine"]].to_numpy()
    nota("arrivo prima dell'ordine", invertite.sum(), "date scambiate")

    oltre = o["qta_ricevuta"] > o["qta_ordinata"]
    o.loc[oltre, "qta_ricevuta"] = o.loc[oltre, "qta_ordinata"]
    nota("ricevuti più degli ordinati", oltre.sum(), "ricevuti portati agli ordinati")

    atteso = o["articolo"].map(listino_vendite)
    diverso = atteso.notna() & (o["prezzo_listino"] != atteso)
    o.loc[diverso, "prezzo_listino"] = atteso[diverso]
    nota("listino diverso da quello delle vendite", diverso.sum(), "preso il listino delle vendite")

    oltre = o["costo_unitario"] > o["prezzo_listino"]
    costo_tipico = o[~oltre].groupby("articolo")["costo_unitario"].agg(lambda s: s.mode()[0])
    if oltre.any():
        o.loc[oltre, "costo_unitario"] = o.loc[oltre, "articolo"].map(costo_tipico).astype(float)
    nota("costo più alto del listino", oltre.sum(), "preso il costo delle altre righe dello stesso articolo")

    return o.reset_index(drop=True), resoconto


def pulisci(vendite, ordini):
    v, r1 = pulisci_vendite(vendite)
    listino_vendite = v.groupby("articolo")["prezzo_listino"].agg(lambda s: s.mode()[0])
    o, r2 = pulisci_ordini(ordini, listino_vendite)

    chiave = ["brand", "categoria", "colore", "stagione", "prezzo_listino"]
    anagrafica = o.drop_duplicates("articolo")[["articolo"] + chiave]
    unici = anagrafica[~anagrafica.duplicated(chiave, keep=False)].set_index(chiave)["articolo"]
    orfani = ~v["articolo"].isin(o["articolo"]) & v["articolo"].notna()
    trovato = pd.Series(list(zip(*[v.loc[orfani, c] for c in chiave])), index=v.index[orfani]).map(unici)
    v.loc[trovato.dropna().index, "articolo"] = trovato.dropna()
    r1.append({"file": "vendite", "regola": "articoli mai ordinati", "righe": int(trovato.notna().sum()),
               "azione": "codice ritrovato negli ordini con brand, categoria, colore, stagione e listino"})
    r1.append({"file": "vendite", "regola": "articoli mai ordinati", "righe": int(trovato.isna().sum()),
               "azione": "tenuti e segnalati: codice non ritrovabile, costo e margine non calcolabili"})

    resoconto = pd.DataFrame(r1 + r2)
    resoconto = resoconto[resoconto["righe"] > 0].reset_index(drop=True)
    return v, o, resoconto
