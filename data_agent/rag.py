import hashlib
import math
import re
from collections import Counter
from pathlib import Path

import chromadb

from config import CHROMA_DIR, KB_TXT

COLLEZIONE = "manuale_la_collina"
STOPWORDS = set("""a ad al alla alle allo agli ai all anche che chi ci come con cosa così da dal dalla dalle dai
degli dei del della delle dello di e è ed fa fino gli ha hanno ho i il in io la le li lo ma mi mai ne nei
nel nella nelle no noi non o per perché più può puo quale quali quando quanto quanti questo questa qui se
si sia sono su sua sue suo sul sulla tra tu un una uno va vi vuole posso possiamo devo deve serve
negli negle state stato fare cosa succede funzionano quale come""".split())


def leggi_sezioni(percorso=KB_TXT) -> list[dict]:
    """Divide il manuale in sezioni [SEZ x.y]: ogni sezione è un documento a sé, con la sua parte."""
    testo = Path(percorso).read_text(encoding="utf-8")
    sezioni, parte = [], ""
    for blocco in re.split(r"\n(?=\[SEZ \d+\.\d+\]|={10,}\nPARTE)", testo):
        intestazione = re.match(r"={10,}\n(PARTE [^\n]+)", blocco)
        if intestazione:
            parte = intestazione.group(1).strip()
            continue
        m = re.match(r"\[SEZ (\d+\.\d+)\] ([^\n]+)\n(.*)", blocco.strip(), re.S)
        if m:
            codice, titolo, corpo = m.groups()
            sezioni.append({"id": codice, "codice": f"SEZ {codice}", "titolo": titolo.strip(),
                            "parte": parte, "testo": f"{titolo.strip()}. {corpo.strip()}"})
    return sezioni


def _parole(testo: str) -> list[str]:
    """Parole senza stopword, ridotte alle prime 5 lettere: profumo e profumi diventano la stessa parola."""
    parole = re.findall(r"[a-zàèéìòù0-9]+", testo.lower())
    return [p[:5] for p in parole if p not in STOPWORDS and len(p) > 1]


class IndiceParole:
    """BM25 sulle sezioni del manuale: affianca la ricerca semantica di ChromaDB."""

    def __init__(self, sezioni, k1=1.5, b=0.75):
        self.sezioni, self.k1, self.b = sezioni, k1, b
        self.doc = [Counter(_parole(s["titolo"] + " " + s["titolo"] + " " + s["testo"])) for s in sezioni]
        self.lung = [sum(c.values()) for c in self.doc]
        self.media = sum(self.lung) / len(self.lung)
        df = Counter(p for c in self.doc for p in c)
        n = len(sezioni)
        self.idf = {p: math.log(1 + (n - f + 0.5) / (f + 0.5)) for p, f in df.items()}

    def classifica(self, domanda: str) -> list[str]:
        q = _parole(domanda)
        punteggi = []
        for s, c, l in zip(self.sezioni, self.doc, self.lung):
            p = sum(self.idf.get(t, 0) * c[t] * (self.k1 + 1) / (c[t] + self.k1 * (1 - self.b + self.b * l / self.media))
                    for t in q if t in c)
            punteggi.append((p, s["id"]))
        return [i for p, i in sorted(punteggi, reverse=True) if p > 0]


class Manuale:
    """Ricerca ibrida nel manuale: ChromaDB (significato) + BM25 (parole), fuse con Reciprocal Rank Fusion."""

    def __init__(self, percorso=KB_TXT, cartella=CHROMA_DIR, embedding_function=None):
        self.sezioni = leggi_sezioni(percorso)
        self.per_id = {s["id"]: s for s in self.sezioni}
        self.parole = IndiceParole(self.sezioni)
        impronta = hashlib.md5(Path(percorso).read_bytes()).hexdigest()[:10]
        client = (chromadb.PersistentClient(path=str(cartella)) if cartella
                  else chromadb.EphemeralClient())
        argomenti = {"embedding_function": embedding_function} if embedding_function else {}
        nome = f"{COLLEZIONE}_{impronta}"
        esistenti = [c.name for c in client.list_collections()]
        for vecchia in [c for c in esistenti if c.startswith(COLLEZIONE) and c != nome]:
            client.delete_collection(vecchia)
        self.collezione = client.get_or_create_collection(nome, metadata={"hnsw:space": "cosine"}, **argomenti)
        if self.collezione.count() != len(self.sezioni):
            self.collezione.upsert(
                ids=[s["id"] for s in self.sezioni],
                documents=[s["testo"] for s in self.sezioni],
                metadatas=[{"codice": s["codice"], "titolo": s["titolo"], "parte": s["parte"]} for s in self.sezioni],
            )

    def cerca(self, domanda: str, k: int = 4) -> list[dict]:
        semantica = self.collezione.query(query_texts=[domanda], n_results=min(10, len(self.sezioni)))
        ordine_sem = semantica["ids"][0]
        distanze = dict(zip(ordine_sem, semantica["distances"][0]))
        ordine_par = self.parole.classifica(domanda)[:10]
        punteggio = Counter()
        for classifica in (ordine_sem, ordine_par):
            for pos, i in enumerate(classifica):
                punteggio[i] += 1 / (60 + pos + 1)
        migliori = [i for i, _ in punteggio.most_common(k)]
        return [{"codice": self.per_id[i]["codice"], "titolo": self.per_id[i]["titolo"],
                 "parte": self.per_id[i]["parte"], "testo": self.per_id[i]["testo"],
                 "similarita": round(1 - distanze[i], 3) if i in distanze else None,
                 "trovata_da": [n for n, c in (("significato", ordine_sem), ("parole", ordine_par)) if i in c]}
                for i in migliori]
