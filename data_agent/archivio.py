"""Archivio operativo dei movimenti grezzi, in SQLite.

In un negozio vero la cassa scrive una riga alla volta, a ogni scontrino o reso: è un carico transazionale,
quello per cui SQLite è fatto. Qui i CSV fanno da importazione iniziale (e vengono reimportati solo se
cambiano), e POST /movimenti aggiunge righe come farebbe la cassa.

Le righe si conservano grezze, così come arrivano (date in due formati, prezzi con la virgola...): la pulizia
resta un passaggio a parte, dichiarato nel resoconto. Quando le analisi le chiedono, le righe escono
dall'archivio come testo CSV e passano dalla stessa lettura dei file, quindi con gli stessi tipi e gli
stessi controlli."""
import csv
import hashlib
import io
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from caricamento import COLONNE_ORDINI, COLONNE_VENDITE, ErroreDati, leggi_csv

TABELLE = {"vendite": COLONNE_VENDITE, "ordini": COLONNE_ORDINI}
# Colonne che una riga di cassa deve avere per forza; le altre possono restare vuote.
OBBLIGATORIE = {
    "vendite": ["id_riga", "data_ora", "scontrino", "articolo", "brand", "categoria", "taglia", "stagione",
                "prezzo_listino", "prezzo_venduto", "sconto_pct", "tipo_movimento"],
    "ordini": ["id_ordine", "articolo", "taglia", "brand", "categoria", "stagione", "data_ordine", "data_arrivo",
               "qta_ordinata", "qta_ricevuta", "costo_unitario", "prezzo_listino"],
}


def _impronta(percorso) -> str:
    return hashlib.sha256(Path(percorso).read_bytes()).hexdigest()


def _testo(valore) -> str | None:
    if valore is None or (isinstance(valore, float) and pd.isna(valore)):
        return None
    testo = str(valore)
    return testo if testo != "" else None


class Archivio:
    def __init__(self, percorso):
        self.percorso = str(percorso)
        self._blocco = threading.Lock()  # una scrittura alla volta; SQLite serializza comunque
        with self._connessione() as con:
            for nome, colonne in TABELLE.items():
                elenco = ", ".join(f'"{c}" TEXT' for c in colonne)
                con.execute(f'CREATE TABLE IF NOT EXISTS {nome} (n INTEGER PRIMARY KEY, {elenco}, '
                            f'origine TEXT NOT NULL, registrato_alle TEXT NOT NULL)')
            con.execute("CREATE TABLE IF NOT EXISTS importazioni (tabella TEXT PRIMARY KEY, impronta TEXT, "
                        "righe INTEGER, importato_alle TEXT)")

    @contextmanager
    def _connessione(self):
        """Una connessione per operazione: conferma alla fine (o annulla se c'è un errore) e si chiude."""
        con = sqlite3.connect(self.percorso, timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")  # chi legge non blocca chi scrive
            with con:
                yield con
        finally:
            con.close()

    def importa_csv(self, percorso, tabella: str) -> int:
        """Importa un CSV, solo se è cambiato dall'ultima importazione. Sostituisce le righe importate da file
        prima, e lascia quelle registrate dalla cassa. Restituisce le righe importate (0 se il file è uguale)."""
        impronta = _impronta(percorso)
        with self._connessione() as con:
            prima = con.execute("SELECT impronta FROM importazioni WHERE tabella = ?", (tabella,)).fetchone()
        if prima and prima[0] == impronta:
            return 0
        df = leggi_csv(percorso, TABELLE[tabella], tabella)  # errore chiaro se il file è malformato
        grezzo = pd.read_csv(percorso, dtype=str, keep_default_na=False)
        adesso = datetime.now().isoformat(timespec="seconds")
        colonne = TABELLE[tabella]
        righe = [[_testo(r[c]) for c in colonne] + ["csv", adesso] for _, r in grezzo[colonne].iterrows()]
        segnaposto = ", ".join("?" * (len(colonne) + 2))
        nomi = ", ".join(f'"{c}"' for c in colonne)
        with self._blocco, self._connessione() as con:
            con.execute(f"DELETE FROM {tabella} WHERE origine = 'csv'")
            con.executemany(f"INSERT INTO {tabella} ({nomi}, origine, registrato_alle) VALUES ({segnaposto})", righe)
            con.execute("INSERT OR REPLACE INTO importazioni VALUES (?, ?, ?, ?)", (tabella, impronta, len(df), adesso))
        return len(righe)

    def registra(self, tabella: str, righe: list[dict]) -> int:
        """Aggiunge righe come farebbe la cassa. Rifiuta colonne sconosciute o obbligatorie mancanti."""
        if tabella not in TABELLE:
            raise ErroreDati(f"Tabella sconosciuta: {tabella}. Valori ammessi: {list(TABELLE)}.")
        colonne = TABELLE[tabella]
        for i, riga in enumerate(righe, start=1):
            sconosciute = sorted(set(riga) - set(colonne))
            if sconosciute:
                raise ErroreDati(f"Riga {i}: colonne sconosciute {sconosciute}.")
            mancanti = [c for c in OBBLIGATORIE[tabella] if _testo(riga.get(c)) is None]
            if mancanti:
                raise ErroreDati(f"Riga {i}: mancano {', '.join(mancanti)}.")
        adesso = datetime.now().isoformat(timespec="seconds")
        valori = [[_testo(r.get(c)) for c in colonne] + ["cassa", adesso] for r in righe]
        segnaposto = ", ".join("?" * (len(colonne) + 2))
        nomi = ", ".join(f'"{c}"' for c in colonne)
        with self._blocco, self._connessione() as con:
            con.executemany(f"INSERT INTO {tabella} ({nomi}, origine, registrato_alle) VALUES ({segnaposto})", valori)
        return len(valori)

    def leggi(self, tabella: str) -> pd.DataFrame:
        """Le righe grezze, nell'ordine di arrivo, tipizzate dalla stessa lettura dei CSV."""
        colonne = TABELLE[tabella]
        with self._connessione() as con:
            nomi = ", ".join(f'"{c}"' for c in colonne)
            righe = con.execute(f"SELECT {nomi} FROM {tabella} "
                                f"ORDER BY origine = 'cassa', n").fetchall()  # prima i file, poi la cassa
        buffer = io.StringIO()
        scrittore = csv.writer(buffer, lineterminator="\n")
        scrittore.writerow(colonne)
        scrittore.writerows([["" if v is None else v for v in r] for r in righe])
        buffer.seek(0)
        return leggi_csv(buffer, colonne, tabella)

    def versione(self) -> dict:
        """Quante righe ci sono e qual è l'ultima: serve a sapere se l'archivio è cambiato dopo il caricamento."""
        with self._connessione() as con:
            return {t: con.execute(f"SELECT COUNT(*), COALESCE(MAX(n), 0) FROM {t}").fetchone() for t in TABELLE}

    def conteggi(self) -> dict:
        with self._connessione() as con:
            return {t: dict(con.execute(f"SELECT origine, COUNT(*) FROM {t} GROUP BY origine").fetchall())
                    for t in TABELLE}
