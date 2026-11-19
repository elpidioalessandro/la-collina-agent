import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
# Un solo .env nella cartella principale, condiviso con il back end. data_agent/.env resta letto per
# compatibilità con le installazioni precedenti; se una variabile è in tutti e due, vince quello principale.
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
VENDITE_CSV = DATA_DIR / "vendite.csv"
ORDINI_CSV = DATA_DIR / "ordini.csv"
KB_TXT = DATA_DIR / "la_collina_kb.txt"

CHART_DIR = Path(os.getenv("CHART_DIR", BASE_DIR / "grafici"))
# I PNG più vecchi di così vengono cancellati (all'avvio e, al massimo ogni 10 minuti, quando se ne salva uno nuovo).
GRAFICI_MAX_ORE = float(os.getenv("GRAFICI_MAX_ORE", 24))
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", BASE_DIR / "chroma_db"))
# Modello di embedding multilingue per il manuale: si scarica qui al primo avvio (circa 135 MB).
EMBEDDING_DIR = Path(os.getenv("EMBEDDING_DIR", Path.home() / ".cache" / "chroma" / "onnx_models" / "multilingue"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = os.getenv("DATA_AGENT_MODEL") or os.getenv("LLM_MODEL") or "openai/gpt-oss-20b"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT") or None

PORT = int(os.getenv("DATA_AGENT_PORT") or os.getenv("PORT") or 8000)
