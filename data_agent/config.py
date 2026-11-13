import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
VENDITE_CSV = DATA_DIR / "vendite.csv"
ORDINI_CSV = DATA_DIR / "ordini.csv"
KB_TXT = DATA_DIR / "la_collina_kb.txt"

CHART_DIR = Path(os.getenv("CHART_DIR", BASE_DIR / "grafici"))
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", BASE_DIR / "chroma_db"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT") or None

PORT = int(os.getenv("PORT", 8000))
