"""Base analitica in DuckDB: i dati puliti, interrogati in SQL.

Dopo la pulizia vendite, ordini e costi finiscono in DuckDB, un database colonnare fatto per le aggregazioni
(somme, conteggi, raggruppamenti) su molte righe. Le analisi principali (incasso, sell-through, resi, margine)
fanno lì i loro GROUP BY; pandas resta per la pulizia e per i controlli riga per riga.

Con un percorso il database sta su file. Ogni caricamento scrive un file nuovo (analitico-<id>.duckdb), lo
riapre in sola lettura e solo allora cancella i precedenti: le domande già in corso finiscono sul file
vecchio, che resta leggibile finché è aperto, e un caricamento a metà non tocca mai quello in uso. Nomi
diversi servono anche perché DuckDB, nello stesso processo, riusa il database già aperto con lo stesso
percorso. Senza percorso sta in memoria (test). Ogni interrogazione usa un suo cursore, quindi più domande
insieme non si intralciano."""
import uuid
from pathlib import Path

import duckdb
import pandas as pd

COLONNE_DATA = {"movimenti": "data_ora", "ordini": "data_arrivo"}
# Valori disponibili da proporre quando un filtro non trova niente: si cercano nella tabella di partenza.
FILTRI_TESTO = ("brand", "categoria", "stagione")


class Analitico:
    def __init__(self, movimenti: pd.DataFrame, ordini: pd.DataFrame, costi: pd.Series, percorso=None):
        base = Path(percorso) if percorso else None
        self.percorso = base.with_name(f"{base.stem}-{uuid.uuid4().hex[:8]}{base.suffix}") if base else None
        if base:
            base.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self.percorso) if self.percorso else ":memory:")
        costi_df = costi.rename("costo_unitario").rename_axis("articolo").reset_index()
        for nome, df in (("movimenti", movimenti), ("ordini", ordini), ("costi", costi_df)):
            con.register("sorgente", df)
            con.execute(f"CREATE TABLE {nome} AS SELECT * FROM sorgente")
            con.unregister("sorgente")
        if self.percorso:
            con.execute("CHECKPOINT")
            con.close()
            con = duckdb.connect(str(self.percorso), read_only=True)
            for vecchio in base.parent.glob(f"{base.stem}-*{base.suffix}*"):
                if vecchio.name != self.percorso.name:
                    vecchio.unlink(missing_ok=True)  # su macOS e Linux chi lo sta leggendo continua a farlo
        self._con = con

    def interroga(self, sql: str, parametri=None) -> pd.DataFrame:
        cursore = self._con.cursor()
        try:
            return cursore.execute(sql, parametri or []).df()
        finally:
            cursore.close()

    def valore(self, sql: str, parametri=None):
        cursore = self._con.cursor()
        try:
            return cursore.execute(sql, parametri or []).fetchone()[0]
        finally:
            cursore.close()

    def dove(self, tabella: str, condizioni=(), data_inizio=None, data_fine=None, brand=None, categoria=None,
             stagione=None) -> tuple[str, list]:
        """Clausola WHERE con i filtri. Se un filtro non trova righe, ValueError con i valori disponibili,
        come i filtri pandas di prima."""
        col_data = COLONNE_DATA[tabella]
        base, parametri = list(condizioni), []
        clausola = lambda parti: ("WHERE " + " AND ".join(parti)) if parti else ""
        if data_inizio:
            base.append(f"{col_data} >= CAST(? AS TIMESTAMP)")
            parametri.append(str(data_inizio))
        if data_fine:
            base.append(f"{col_data} < CAST(? AS TIMESTAMP) + INTERVAL 1 DAY")
            parametri.append(str(data_fine))
        for colonna, valore in (("brand", brand), ("categoria", categoria), ("stagione", stagione)):
            if not valore:
                continue
            prova = base + [f"lower({colonna}) = lower(?)"]
            if not self.valore(f"SELECT COUNT(*) FROM {tabella} {clausola(prova)}", parametri + [str(valore)]):
                disponibili = self.interroga(
                    f"SELECT DISTINCT CAST({colonna} AS VARCHAR) AS v FROM {tabella} "
                    f"{clausola(list(condizioni))} ORDER BY v")["v"].dropna().tolist()
                raise ValueError(f"Nessun dato per {colonna} = '{valore}'. Valori disponibili: {disponibili}.")
            base, parametri = prova, parametri + [str(valore)]
        if not self.valore(f"SELECT COUNT(*) FROM {tabella} {clausola(base)}", parametri):
            primo, ultimo = self.interroga(
                f"SELECT MIN({col_data}) AS a, MAX({col_data}) AS b FROM {tabella} {clausola(list(condizioni))}").iloc[0]
            raise ValueError(f"Nessun dato nel periodo {data_inizio} - {data_fine}. Dati disponibili dal "
                             f"{primo:%Y-%m-%d} al {ultimo:%Y-%m-%d}.")
        return clausola(base), parametri


def raggruppa(analitico: Analitico, tabella: str, chiave: str | None, misure: str, dove: str, parametri: list,
              indice: str = "totale") -> pd.DataFrame:
    """GROUP BY in DuckDB. Senza chiave una sola riga, con indice 'totale', come i raggruppamenti di prima.
    L'ordine è quello della chiave, lo stesso di pandas groupby."""
    if chiave:
        # pandas groupby scarta le righe con la chiave vuota: qui lo stesso.
        filtro = f"{dove} AND {chiave} IS NOT NULL" if dove else f"WHERE {chiave} IS NOT NULL"
        t = analitico.interroga(f"SELECT {chiave}, {misure} FROM {tabella} {filtro} GROUP BY {chiave} "
                                f"ORDER BY {chiave}", parametri)
        return t.set_index(chiave)
    t = analitico.interroga(f"SELECT {misure} FROM {tabella} {dove}", parametri)
    t.index = [indice]
    return t
