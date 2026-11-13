import pandas as pd

SCAGLIONI = {1: 30, 2: 30, 3: 40, 4: 50, 5: 60, 6: 60, 7: 70, 8: 70}
GIORNI_DIVIETO_PROMO = 30


def inizio_saldi_invernali(anno: int) -> pd.Timestamp:
    """Primo giorno feriale prima dell'Epifania; se cade di lunedì si anticipa al sabato."""
    giorno = pd.Timestamp(f"{anno}-01-05")
    if giorno.day_of_week == 6:
        giorno -= pd.Timedelta(days=1)
    elif giorno.day_of_week == 0:
        giorno -= pd.Timedelta(days=2)
    return giorno


def inizio_saldi_estivi(anno: int) -> pd.Timestamp:
    """Primo sabato di luglio."""
    giorno = pd.Timestamp(f"{anno}-07-01")
    return giorno + pd.Timedelta(days=(5 - giorno.day_of_week) % 7)


def periodi_saldi(primo_anno: int, ultimo_anno: int) -> pd.DataFrame:
    """Una riga per ogni periodo di saldi: stagione in saldo, inizio e fine (8 settimane)."""
    righe = []
    for anno in range(primo_anno - 1, ultimo_anno + 1):
        inizio = inizio_saldi_invernali(anno + 1)
        righe.append({"stagione": f"AI{anno % 100:02d}", "inizio": inizio,
                      "fine": inizio + pd.Timedelta(weeks=8) - pd.Timedelta(days=1)})
        inizio = inizio_saldi_estivi(anno)
        righe.append({"stagione": f"PE{anno % 100:02d}", "inizio": inizio,
                      "fine": inizio + pd.Timedelta(weeks=8) - pd.Timedelta(days=1)})
    return pd.DataFrame(righe).sort_values("inizio", ignore_index=True)


def info_saldi(date: pd.Series, saldi: pd.DataFrame) -> pd.DataFrame:
    """Per ogni data: stagione in saldo, scaglione atteso e se cade nei 30 giorni di divieto promo."""
    giorno = date.dt.normalize()
    out = pd.DataFrame(index=date.index, data={"stagione_in_saldo": None, "sconto_scaglione": float("nan"),
                                               "divieto_promo": False})
    for s in saldi.itertuples():
        dentro = (giorno >= s.inizio) & (giorno <= s.fine)
        settimana = ((giorno[dentro] - s.inizio).dt.days // 7 + 1)
        out.loc[dentro, "stagione_in_saldo"] = s.stagione
        out.loc[dentro, "sconto_scaglione"] = settimana.map(SCAGLIONI).astype(float)
        prima = (giorno >= s.inizio - pd.Timedelta(days=GIORNI_DIVIETO_PROMO)) & (giorno < s.inizio)
        out.loc[prima, "divieto_promo"] = True
    return out
