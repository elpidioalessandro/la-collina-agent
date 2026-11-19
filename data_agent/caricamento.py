"""Lettura dei CSV di vendite e ordini, con errori chiari se un file è mancante, vuoto o malformato.

Gli errori di struttura (file, separatore, colonne, valori non numerici) fermano il caricamento: meglio un
messaggio chiaro all'avvio che un'analisi su dati sbagliati. Gli errori di registrazione riga per riga
(date scritte male, prezzi con la virgola...) li gestisce invece la pulizia, che li dichiara."""
from pathlib import Path

import pandas as pd

COLONNE_VENDITE = ["id_riga", "data_ora", "scontrino", "articolo", "brand", "categoria", "taglia", "colore",
                   "stagione", "prezzo_listino", "prezzo_venduto", "sconto_pct", "motivo_sconto", "tipo_movimento",
                   "rif_vendita", "esito_reso", "motivo_reso", "metodo_pagamento", "id_buono", "reso_fornitore"]
COLONNE_ORDINI = ["id_ordine", "articolo", "taglia", "brand", "fornitore", "modalita_acquisto", "categoria", "colore",
                  "stagione", "tipo_ordine", "data_ordine", "data_arrivo", "qta_ordinata", "qta_ricevuta",
                  "costo_unitario", "prezzo_listino"]
# prezzo_venduto non c'è: può contenere la virgola, e la pulizia lo converte e lo dichiara.
NUMERICHE = {"vendite": ["prezzo_listino", "sconto_pct"],
             "ordini": ["qta_ordinata", "qta_ricevuta", "costo_unitario", "prezzo_listino"]}


class ErroreDati(ValueError):
    """Un file di dati non si può usare così com'è. Il messaggio dice quale file e cosa correggere."""


def leggi_csv(percorso, colonne: list[str], nome: str) -> pd.DataFrame:
    p = Path(percorso)
    if not p.is_file():
        raise ErroreDati(f"{nome}: file non trovato ({p}).")
    if p.stat().st_size == 0:
        raise ErroreDati(f"{nome}: il file è vuoto.")
    try:
        df = pd.read_csv(p)
    except pd.errors.EmptyDataError:
        raise ErroreDati(f"{nome}: il file è vuoto.") from None
    except UnicodeDecodeError:
        raise ErroreDati(f"{nome}: il file non è in UTF-8. Salvalo di nuovo come CSV UTF-8.") from None
    except pd.errors.ParserError as e:
        raise ErroreDati(f"{nome}: il file non è un CSV valido ({str(e).strip()}).") from None

    if len(df.columns) == 1 and ";" in str(df.columns[0]):
        raise ErroreDati(f"{nome}: il separatore è il punto e virgola; serve la virgola (CSV standard).")
    mancanti = [c for c in colonne if c not in df.columns]
    if mancanti:
        raise ErroreDati(f"{nome}: mancano le colonne {', '.join(mancanti)}.")
    if df.empty:
        raise ErroreDati(f"{nome}: c'è solo l'intestazione, nessuna riga di dati.")

    for colonna in NUMERICHE.get(nome, []):
        valori = df[colonna]
        convertiti = pd.to_numeric(valori, errors="coerce")
        sbagliati = valori.notna() & convertiti.isna()
        if sbagliati.any():
            indice = sbagliati.idxmax()
            raise ErroreDati(f"{nome}: la colonna {colonna} ha {int(sbagliati.sum())} valori non numerici "
                             f"(il primo alla riga {indice + 2}: '{valori[indice]}').")
        df[colonna] = convertiti
    return df


def leggi_vendite(percorso) -> pd.DataFrame:
    return leggi_csv(percorso, COLONNE_VENDITE, "vendite")


def leggi_ordini(percorso) -> pd.DataFrame:
    return leggi_csv(percorso, COLONNE_ORDINI, "ordini")
