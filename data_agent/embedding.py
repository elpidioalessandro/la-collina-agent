"""Embedding multilingue per la ricerca nel manuale.

Il modello predefinito di ChromaDB (all-MiniLM-L6-v2) è addestrato sull'inglese: sulle domande in italiano
con sinonimi non aiutava (vedi valuta_rag.py). Qui si usa paraphrase-multilingual-MiniLM-L12-v2, addestrato a
riconoscere frasi con lo stesso significato in 50 lingue, nella versione ONNX quantizzata (118 MB).
Gira con onnxruntime e tokenizers, che arrivano già con chromadb: nessuna dipendenza in più.
Al primo avvio i file si scaricano da Hugging Face nella cartella EMBEDDING_DIR."""
import os
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

import config
from registro import registro

log = registro("embedding")
MODELLO = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
FILE = {
    "model_quantized.onnx": f"https://huggingface.co/{MODELLO}/resolve/main/onnx/model_quantized.onnx",
    "tokenizer.json": f"https://huggingface.co/{MODELLO}/resolve/main/tokenizer.json",
}
LUNGHEZZA_MASSIMA = 256  # token: le sezioni del manuale più lunghe stanno sotto


def scarica_modello(cartella: Path) -> None:
    cartella.mkdir(parents=True, exist_ok=True)
    for nome, url in FILE.items():
        destinazione = cartella / nome
        if destinazione.is_file() and destinazione.stat().st_size > 0:
            continue
        log.info("scarico il modello di embedding", extra={"file": nome, "da": url})
        with tempfile.NamedTemporaryFile(dir=cartella, delete=False) as tmp, urllib.request.urlopen(url, timeout=60) as r:
            while blocco := r.read(1 << 20):
                tmp.write(blocco)
        os.replace(tmp.name, destinazione)


class EmbeddingMultilingue(EmbeddingFunction[Documents]):
    """Media dei vettori dei token (mean pooling) normalizzata: lo stesso calcolo di sentence-transformers."""

    def __init__(self, cartella: str | Path | None = None):
        self.cartella = Path(cartella or config.EMBEDDING_DIR)
        self._sessione = self._tokenizer = None

    def _carica(self):
        if self._sessione is not None:
            return
        import onnxruntime
        from tokenizers import Tokenizer

        scarica_modello(self.cartella)
        self._tokenizer = Tokenizer.from_file(str(self.cartella / "tokenizer.json"))
        self._tokenizer.enable_truncation(LUNGHEZZA_MASSIMA)
        self._tokenizer.enable_padding()
        opzioni = onnxruntime.SessionOptions()
        opzioni.log_severity_level = 3
        self._sessione = onnxruntime.InferenceSession(str(self.cartella / "model_quantized.onnx"), opzioni,
                                                      providers=["CPUExecutionProvider"])
        self._ingressi = {i.name for i in self._sessione.get_inputs()}

    def __call__(self, input: Documents) -> Embeddings:
        self._carica()
        codifiche = self._tokenizer.encode_batch(list(input))
        ids = np.array([c.ids for c in codifiche], dtype=np.int64)
        maschera = np.array([c.attention_mask for c in codifiche], dtype=np.int64)
        ingressi = {"input_ids": ids, "attention_mask": maschera}
        if "token_type_ids" in self._ingressi:
            ingressi["token_type_ids"] = np.zeros_like(ids)
        token = self._sessione.run(None, ingressi)[0]
        pesi = maschera[..., None].astype(np.float32)
        media = (token * pesi).sum(axis=1) / np.clip(pesi.sum(axis=1), 1e-9, None)
        media /= np.clip(np.linalg.norm(media, axis=1, keepdims=True), 1e-12, None)
        return [v.astype(np.float32) for v in media]

    @staticmethod
    def name() -> str:
        return "multilingue_minilm_l12"

    def get_config(self) -> dict:
        return {"cartella": str(self.cartella)}

    @staticmethod
    def build_from_config(config_salvata: dict) -> "EmbeddingMultilingue":
        return EmbeddingMultilingue(config_salvata.get("cartella"))
