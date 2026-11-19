"""Misura la ricerca nel manuale: solo parole (BM25), solo significato (embedding inglese di ChromaDB o
multilingue) e fusione con BM25 (RRF). La fusione con l'embedding multilingue è quella usata dall'assistente.

    python valuta_rag.py              tabella in markdown
    python valuta_rag.py --dettagli   anche le domande sbagliate, per configurazione

Le domande sono in valutazione/domande_rag.csv, in due gruppi: con le parole del manuale e con sinonimi
(«acqua di colonia» invece di «profumo», «svendita» invece di «saldi»). Una risposta è giusta se una delle
sezioni attese compare tra le prime k. Usa i veri modelli di embedding: la prima volta li scarica."""
import argparse
import csv

import config
from rag import Manuale

DOMANDE = config.ROOT_DIR / "valutazione" / "domande_rag.csv"
K = 6  # l'orchestratore legge le prime 6 sezioni (con --k si misura un altro valore)


def leggi_domande(percorso=DOMANDE) -> list[dict]:
    with open(percorso, encoding="utf-8") as f:
        return [{**r, "attese": set(r["sezioni_attese"].split("|"))} for r in csv.DictReader(f)]


def manuali() -> dict[str, Manuale]:
    """Lo stesso manuale indicizzato con i due modelli, ognuno in una cartella temporanea: non tocca
    l'indice dell'assistente, e i due indici non si cancellano a vicenda."""
    import tempfile

    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    from embedding import EmbeddingMultilingue

    return {"inglese": Manuale(cartella=tempfile.mkdtemp(), embedding_function=DefaultEmbeddingFunction()),
            "multilingue": Manuale(cartella=tempfile.mkdtemp(), embedding_function=EmbeddingMultilingue())}


def classifiche(m: dict[str, Manuale], domanda: str) -> dict[str, list[str]]:
    inglese, _ = m["inglese"].classifica_significato(domanda)
    multilingue, _ = m["multilingue"].classifica_significato(domanda)
    parole = m["multilingue"].parole.classifica(domanda)[:10]
    return {"solo parole (BM25)": parole,
            "solo embedding inglese (all-MiniLM-L6-v2)": inglese,
            "solo embedding multilingue (paraphrase-multilingual-MiniLM-L12-v2)": multilingue,
            "BM25 + embedding inglese (prima)": Manuale.fondi(inglese, parole),
            "BM25 + embedding multilingue (ora)": Manuale.fondi(multilingue, parole)}


def misura(m: dict[str, Manuale], domande: list[dict]) -> dict:
    """Per configurazione e gruppo: giuste al primo posto, giuste tra le prime K, MRR."""
    esiti = {}
    for d in domande:
        for nome, ordine in classifiche(m, d["domanda"]).items():
            posizione = next((i + 1 for i, s in enumerate(ordine) if s in d["attese"]), None)
            for gruppo in (d["tipo"], "tutte"):
                e = esiti.setdefault(nome, {}).setdefault(gruppo, {"n": 0, "primo": 0, "top_k": 0, "rr": 0.0, "sbagliate": []})
                e["n"] += 1
                e["primo"] += posizione == 1
                e["top_k"] += bool(posizione and posizione <= K)
                e["rr"] += 1 / posizione if posizione else 0
                if gruppo != "tutte" and not (posizione and posizione <= K):
                    e["sbagliate"].append(f"{d['domanda']} → attesa {d['sezioni_attese']}, trovate {ordine[:K]}")
    return esiti


def tabella(esiti: dict) -> str:
    gruppi = [g for g in ("parole del manuale", "sinonimi", "tutte") if g in next(iter(esiti.values()))]
    righe = ["| Configurazione | " + " | ".join(f"{g}: 1ª / prime {K} / MRR" for g in gruppi) + " |",
             "|---|" + "---|" * len(gruppi)]
    for nome, per_gruppo in esiti.items():
        celle = []
        for g in gruppi:
            e = per_gruppo[g]
            celle.append(f"{e['primo']}/{e['n']} · {e['top_k']}/{e['n']} · {e['rr'] / e['n']:.2f}")
        righe.append(f"| {nome} | " + " | ".join(celle) + " |")
    return "\n".join(righe)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dettagli", action="store_true")
    parser.add_argument("--k", type=int, default=K, help="sezioni considerate (default 6)")
    args = parser.parse_args()
    K = args.k
    esiti = misura(manuali(), leggi_domande())
    print(tabella(esiti))
    if args.dettagli:
        for nome, per_gruppo in esiti.items():
            sbagliate = [s for g, e in per_gruppo.items() if g != "tutte" for s in e["sbagliate"]]
            print(f"\n{nome}: {len(sbagliate)} fuori dalle prime {K}")
            for s in sbagliate:
                print(f"  - {s}")
