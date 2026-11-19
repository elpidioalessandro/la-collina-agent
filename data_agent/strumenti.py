import contextlib
import contextvars
import io
import json
import threading
import traceback
from dataclasses import dataclass, field

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from langchain_core.tools import tool

import analisi
import grafici

MAX_TENTATIVI_CODICE = 3


@dataclass
class StatoDomanda:
    """Stato di una sola domanda: dati su cui lavorare, grafici creati e tentativi di codice.
    Vive in una ContextVar, quindi due domande in parallelo non si vedono a vicenda."""
    dati: analisi.Dati
    grafici: list = field(default_factory=list)
    tentativi_codice: int = 0


_STATO: contextvars.ContextVar[StatoDomanda] = contextvars.ContextVar("stato_domanda")
# pyplot ha uno stato globale (le figure aperte): il codice che lo usa passa da qui una domanda alla volta.
_PYPLOT = threading.Lock()


def nuova_domanda(dati: analisi.Dati) -> StatoDomanda:
    """Apre lo stato di una domanda nel contesto corrente e lo restituisce."""
    stato = StatoDomanda(dati)
    _STATO.set(stato)
    return stato


def stato_corrente() -> StatoDomanda:
    try:
        return _STATO.get()
    except LookupError:
        raise RuntimeError("Nessuna domanda in corso: chiama nuova_domanda(dati) prima degli strumenti.") from None


def _json(risultato) -> str:
    return json.dumps(risultato, ensure_ascii=False, default=str)[:8000]


def _esegui(funzione, *args, **kwargs) -> str:
    """Esegue un'analisi e trasforma gli errori in messaggi leggibili per l'agente."""
    try:
        filtri = {k: v for k, v in kwargs.items() if v not in (None, "")}
        return _json(funzione(stato_corrente().dati, *args, **filtri))
    except ValueError as e:
        return f"ERRORE: {e}"


@tool
def info_dati() -> str:
    """Periodo coperto dai dati, anni completi, brand, categorie, stagioni e date dei saldi."""
    return _esegui(analisi.info_dati)


@tool
def incasso(raggruppa_per: str = "nessuno", data_inizio: str | None = None, data_fine: str | None = None,
            brand: str | None = None, categoria: str | None = None, stagione: str | None = None) -> str:
    """Incasso delle vendite in euro, pezzi venduti, scontrini e sconto medio.
    raggruppa_per: 'nessuno', 'anno', 'mese', 'stagione', 'brand', 'categoria' o 'motivo' (motivo dello sconto).
    Date AAAA-MM-GG, estremi inclusi. stagione: es. 'AI24' (autunno-inverno 2024) o 'PE25'."""
    return _esegui(analisi.incasso, raggruppa_per, data_inizio=data_inizio, data_fine=data_fine,
                   brand=brand, categoria=categoria, stagione=stagione)


@tool
def sell_through(raggruppa_per: str = "brand", stagione: str | None = None, brand: str | None = None,
                 categoria: str | None = None) -> str:
    """Sell-through: pezzi venduti diviso pezzi ricevuti, in totale e a prezzo pieno.
    raggruppa_per: 'nessuno', 'brand', 'categoria' o 'stagione'. Ordinato dal valore più basso."""
    return _esegui(analisi.sell_through, raggruppa_per, stagione=stagione, brand=brand, categoria=categoria)


@tool
def confronta_stagioni(stagione: str, brand: str | None = None, categoria: str | None = None) -> str:
    """Come è andata una categoria o un brand in una stagione, confrontata con la stessa stagione dell'anno
    prima e dell'anno dopo: sell-through, pezzi, incasso, con una sintesi già calcolata da riportare.
    Usalo per "è andato bene/male", "perché X è andato male nel 2024", "com'è andata la stagione".
    stagione: 'AI24' per l'inverno 2024 (capospalla e maglia si vendono in AI), 'PE24' per l'estate 2024
    (costumi in PE). Se la categoria si vende tutto l'anno e l'utente dice solo l'anno, chiamalo per PE e per AI."""
    return _esegui(analisi.confronta_stagioni, stagione, brand=brand, categoria=categoria)


@tool
def soglie_fornitori(stagione: str | None = None) -> str:
    """Quali brand superano le soglie di controllo dei fornitori e vanno segnalati al titolare per rinegoziazione
    (almeno due soglie nella stessa stagione): resi per difetto, sell-through, consegne incomplete, sconto medio.
    stagione: 'AI24', 'PE25'...; senza stagione controlla tutte le stagioni."""
    return _esegui(analisi.soglie_fornitori, stagione)


@tool
def resi(raggruppa_per: str = "brand", motivo: str | None = None, data_inizio: str | None = None,
         data_fine: str | None = None, brand: str | None = None, categoria: str | None = None,
         stagione: str | None = None) -> str:
    """Resi in numero e in percentuale sui pezzi venduti dello stesso gruppo.
    raggruppa_per: 'nessuno', 'anno', 'mese', 'stagione', 'brand', 'categoria', 'motivo' o
    'brand_motivo' (tabella brand x motivo: la scelta migliore per confrontare i resi di un brand con gli altri).
    motivo: 'taglia', 'difetto', 'ripensamento' o 'regalo'; se omesso, tutti i resi."""
    return _esegui(analisi.resi, raggruppa_per, motivo=motivo, data_inizio=data_inizio, data_fine=data_fine,
                   brand=brand, categoria=categoria, stagione=stagione)


@tool
def margine(raggruppa_per: str = "brand", data_inizio: str | None = None, data_fine: str | None = None,
            brand: str | None = None, categoria: str | None = None, stagione: str | None = None) -> str:
    """Margine lordo: incasso meno costo d'acquisto dei pezzi venduti, in euro e in percentuale sull'incasso.
    raggruppa_per: 'nessuno', 'anno', 'mese', 'stagione', 'brand' o 'categoria'."""
    return _esegui(analisi.margine, raggruppa_per, data_inizio=data_inizio, data_fine=data_fine,
                   brand=brand, categoria=categoria, stagione=stagione)


@tool
def sconti(raggruppa_per: str = "motivo", data_inizio: str | None = None, data_fine: str | None = None,
           brand: str | None = None, categoria: str | None = None, stagione: str | None = None) -> str:
    """Euro concessi in sconti (listino meno prezzo pagato) e percentuale sul listino.
    raggruppa_per: 'motivo' (saldo, cliente abituale, nessuno), 'nessuno', 'anno', 'mese', 'stagione',
    'brand' o 'categoria'."""
    return _esegui(analisi.sconti, raggruppa_per, data_inizio=data_inizio, data_fine=data_fine,
                   brand=brand, categoria=categoria, stagione=stagione)


@tool
def controlli_regole() -> str:
    """Violazioni delle regole del negozio trovate nei dati: orari, sconti oltre il tetto, promozioni vietate,
    profumi in saldo, resi oltre 14 giorni, difetti non rimandati al fornitore, buoni scaduti, consegne
    incomplete. Per ogni violazione: numero di casi, sezione del manuale violata ed esempi."""
    return _esegui(analisi.controlli)


@tool
def resoconto_pulizia() -> str:
    """Correzioni fatte ai dati prima dell'analisi: righe duplicate eliminate, date, prezzi, sconti, taglie,
    brand e colori corretti, codici articolo ritrovati. Usalo per domande sulla qualità dei dati."""
    return _esegui(analisi.resoconto_pulizia)


@tool
def crea_grafico(metrica: str, raggruppa_per: str, motivo: str | None = None, data_inizio: str | None = None,
                 data_fine: str | None = None, brand: str | None = None, categoria: str | None = None,
                 stagione: str | None = None) -> str:
    """Crea un grafico PNG e lo mostra all'utente.
    metrica: 'incasso', 'sell_through', 'resi', 'margine' o 'sconti'.
    raggruppa_per: 'anno', 'mese' (grafico a linee), 'stagione', 'brand', 'categoria' o 'motivo'.
    motivo: solo per i resi ('taglia', 'difetto', 'ripensamento', 'regalo')."""
    stato = stato_corrente()
    try:
        filtri = {k: v for k, v in dict(data_inizio=data_inizio, data_fine=data_fine, brand=brand,
                                         categoria=categoria, stagione=stagione).items() if v}
        nome = grafici.crea_grafico(stato.dati, metrica, raggruppa_per, motivo=motivo, **filtri)
    except ValueError as e:
        return f"ERRORE: {e}"
    stato.grafici.append(nome)
    funzione, colonna, _ = grafici.METRICHE[metrica]
    argomenti = {**filtri, **({"motivo": motivo} if metrica == "resi" and motivo else {})}
    if metrica == "sell_through":
        argomenti = {k: v for k, v in argomenti.items() if k in ("stagione", "brand", "categoria")}
    risultato = funzione(stato.dati, raggruppa_per, **argomenti)
    valori = {str(r[next(iter(r))]): r[colonna] for r in risultato["tabella"]}
    contesto = {k: v for k, v in risultato.items() if k not in ("tabella", "righe_usate", "righe_ordini_usate")}
    return _json({"grafico": f"creato e già mostrato all'utente ({nome})", "valori_nel_grafico": valori, **contesto,
                  "istruzione": "Riporta nella risposta i numeri chiave (il più alto e il più basso), non descrivere il grafico."})


@tool
def esegui_codice_pandas(codice: str) -> str:
    """Esegue codice Python/pandas per domande che gli altri strumenti non coprono.
    DataFrame disponibili (già puliti): `vendite` (una riga per movimento di cassa: colonne data_ora, scontrino,
    articolo, brand, categoria, taglia, colore, stagione, prezzo_listino, prezzo_venduto, sconto_pct,
    motivo_sconto, tipo_movimento ['vendita','reso','buono_regalo'], rif_vendita, esito_reso, motivo_reso,
    metodo_pagamento, id_buono, reso_fornitore, anno, mese) e `ordini` (articolo, taglia, brand, fornitore,
    modalita_acquisto, categoria, colore, stagione, tipo_ordine, data_ordine, data_arrivo, qta_ordinata,
    qta_ricevuta, costo_unitario, prezzo_listino). Sono disponibili `pd`, `np` e `plt`.
    Per le vendite filtra tipo_movimento == 'vendita'. Salva il risultato nella variabile `risultato`.
    Se crei una figura con plt, viene salvata e mostrata all'utente."""
    stato = stato_corrente()
    if stato.tentativi_codice >= MAX_TENTATIVI_CODICE:
        return ("ERRORE: raggiunto il limite di tentativi. Non riprovare: spiega all'utente che non è stato "
                "possibile calcolare il dato e proponi una domanda alternativa.")
    stato.tentativi_codice += 1
    d = stato.dati
    spazio = {"vendite": d.v.copy(), "ordini": d.o.copy(), "pd": pd, "np": np, "plt": plt}
    uscita = io.StringIO()
    # redirect_stdout e le figure di pyplot sono globali al processo: una domanda alla volta.
    with _PYPLOT:
        plt.close("all")
        try:
            with contextlib.redirect_stdout(uscita):
                exec(codice, spazio)
        except Exception:
            errore = traceback.format_exc(limit=1).strip().splitlines()[-1]
            plt.close("all")
            return (f"ERRORE nel codice (tentativo {stato.tentativi_codice}/{MAX_TENTATIVI_CODICE}): {errore}. "
                    "Correggi il codice e riprova.")
        for numero in plt.get_fignums():
            stato.grafici.append(grafici.salva(plt.figure(numero)))
    risultato = spazio.get("risultato", spazio.get("result"))
    if risultato is None:
        risultato = uscita.getvalue() or "Nessun risultato: assegna il valore alla variabile `risultato`."
    if isinstance(risultato, (pd.DataFrame, pd.Series)):
        risultato = risultato.round(2).to_string()
    return str(risultato)[:2000]


STRUMENTI = [info_dati, incasso, sell_through, confronta_stagioni, soglie_fornitori, resi, margine, sconti, controlli_regole, resoconto_pulizia,
             crea_grafico, esegui_codice_pandas]
