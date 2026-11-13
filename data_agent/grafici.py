import uuid
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.ticker import FuncFormatter

import analisi
from config import CHART_DIR

sns.set_theme(style="whitegrid")
COLORE = "#2F4F4F"
COLORE_TENUE = "#A9B8B8"

METRICHE = {
    "incasso": (analisi.incasso, "incasso_euro", "Incasso (€)"),
    "sell_through": (analisi.sell_through, "sell_through_pct", "Sell-through (%)"),
    "resi": (analisi.resi, "pct_sui_venduti", "Resi sui venduti (%)"),
    "margine": (analisi.margine, "margine_pct", "Margine lordo (%)"),
    "sconti": (analisi.sconti, "sconto_euro", "Sconti concessi (€)"),
}
ETICHETTE = {"anno": "anno", "mese": "mese", "stagione": "stagione", "brand": "brand",
             "categoria": "categoria", "motivo": "motivo"}


def _numero(y: float) -> str:
    testo = f"{y:,.0f}" if abs(y) >= 100 else f"{y:,.1f}"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".")


def salva(fig) -> str:
    """Salva la figura come PNG nella cartella dei grafici e restituisce il nome del file."""
    Path(CHART_DIR).mkdir(parents=True, exist_ok=True)
    nome = f"{uuid.uuid4().hex[:12]}.png"
    fig.savefig(Path(CHART_DIR) / nome, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return nome


def crea_grafico(d, metrica: str, raggruppa_per: str, motivo: str = None, **filtri) -> str:
    if metrica not in METRICHE:
        raise ValueError(f"metrica deve essere una tra {list(METRICHE)}.")
    if raggruppa_per == "nessuno":
        raise ValueError("Per un grafico serve un raggruppamento: anno, mese, stagione, brand o categoria.")
    funzione, colonna, etichetta = METRICHE[metrica]
    argomenti = dict(filtri)
    if metrica == "resi" and motivo:
        argomenti["motivo"] = motivo
    if metrica == "sell_through":
        argomenti = {k: v for k, v in argomenti.items() if k in ("stagione", "brand", "categoria")}
    risultato = funzione(d, raggruppa_per, **argomenti)
    t = pd.DataFrame(risultato["tabella"])
    t = t.set_index(t.columns[0])[colonna]

    fig, ax = plt.subplots(figsize=(10, 4.8))
    if raggruppa_per == "mese":
        t = t.sort_index()
        ax.plot(range(len(t)), t.values, marker="o", color=COLORE)
        passo = max(1, len(t) // 12)
        ax.set_xticks(range(0, len(t), passo), t.index[::passo], rotation=45, ha="right")
    else:
        if raggruppa_per in ("anno", "stagione"):
            t = t.sort_index()
        colori = [COLORE] * len(t)
        if metrica == "incasso" and raggruppa_per == "anno":
            completi = analisi.info_dati(d)["anni_completi"]
            colori = [COLORE if int(a) in completi else COLORE_TENUE for a in t.index]
        ax.bar([str(i) for i in t.index], t.values, color=colori)
        if len(t) > 5:
            plt.setp(ax.get_xticklabels(), rotation=35, ha="right", rotation_mode="anchor")
        for x, y in enumerate(t.values):
            ax.annotate(_numero(y), (x, y), ha="center", va="bottom", fontsize=9)
        if metrica == "incasso" and raggruppa_per == "anno":
            ax.set_title("Incasso per anno (in chiaro gli anni parziali)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: _numero(y)))
    ax.set_ylabel(etichetta)
    ax.set_xlabel(ETICHETTE.get(raggruppa_per, raggruppa_per))
    if not ax.get_title():
        titolo = f"{etichetta} per {ETICHETTE.get(raggruppa_per, raggruppa_per)}"
        if motivo:
            titolo += f" – motivo: {motivo}"
        dettagli = [f"{k} {v}" for k, v in filtri.items() if v]
        ax.set_title(titolo + (f" ({', '.join(dettagli)})" if dettagli else ""))
    return salva(fig)
