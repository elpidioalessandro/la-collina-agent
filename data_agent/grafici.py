import threading
import time
import uuid
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure
import seaborn as sns
from matplotlib.ticker import FuncFormatter

import analisi
from config import CHART_DIR, GRAFICI_MAX_ORE
from registro import registro

log = registro("grafici")
_PULIZIA = {"ultima": 0.0, "blocco": threading.Lock()}
INTERVALLO_PULIZIA_S = 600

sns.set_theme(style="white", rc={"axes.edgecolor": "#bdb8af", "axes.labelcolor": "#3e3530", "xtick.color": "#3e3530", "ytick.color": "#74706a", "axes.titleweight": "normal", "axes.titlesize": 13, "axes.spines.top": False, "axes.spines.right": False})
COLORE = "#3E3530"
COLORE_TENUE = "#CFC9BE"

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


def pulisci_vecchi(max_ore: float | None = None, adesso: float | None = None) -> int:
    """Cancella i PNG più vecchi di max_ore (default GRAFICI_MAX_ORE). Restituisce quanti ne ha cancellati."""
    cartella = Path(CHART_DIR)
    if not cartella.is_dir():
        return 0
    ore = GRAFICI_MAX_ORE if max_ore is None else max_ore
    limite = (adesso or time.time()) - ore * 3600
    cancellati = 0
    for file in cartella.glob("*.png"):
        try:
            if file.stat().st_mtime < limite:
                file.unlink()
                cancellati += 1
        except FileNotFoundError:
            pass  # cancellato nel frattempo da un'altra richiesta
    if cancellati:
        log.info("grafici vecchi cancellati", extra={"cancellati": cancellati, "piu_vecchi_di_ore": ore})
    return cancellati


def _pulizia_periodica() -> None:
    with _PULIZIA["blocco"]:
        if time.time() - _PULIZIA["ultima"] < INTERVALLO_PULIZIA_S:
            return
        _PULIZIA["ultima"] = time.time()
    pulisci_vecchi()


def salva(fig) -> str:
    """Salva la figura come PNG nella cartella dei grafici e restituisce il nome del file."""
    _pulizia_periodica()
    Path(CHART_DIR).mkdir(parents=True, exist_ok=True)
    nome = f"{uuid.uuid4().hex[:12]}.png"
    fig.savefig(Path(CHART_DIR) / nome, dpi=120, bbox_inches="tight")
    plt.close(fig)  # per le figure di pyplot; su una Figure creata a parte non fa nulla
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

    # Figure creata senza pyplot: non tocca lo stato globale, quindi è sicura con più domande in parallelo.
    fig = Figure(figsize=(10, 4.8))
    ax = fig.subplots()
    if raggruppa_per == "mese":
        t = t.sort_index()
        ax.plot(range(len(t)), t.values, marker="o", markersize=4, linewidth=1.6, color=COLORE)
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
            ax.tick_params(axis="x", labelrotation=35)
            for etichetta_x in ax.get_xticklabels():
                etichetta_x.set_horizontalalignment("right")
                etichetta_x.set_rotation_mode("anchor")
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
