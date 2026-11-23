import sys
from pathlib import Path

import pytest

CARTELLA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARTELLA.parent))
sys.path.insert(0, str(CARTELLA))

import config  # noqa: E402


@pytest.fixture(scope="session")
def dati():
    import analisi
    return analisi.Dati.da_csv(config.VENDITE_CSV, config.ORDINI_CSV)


@pytest.fixture(scope="session")
def manuale():
    from finti import EmbeddingFinto
    from rag import Manuale
    return Manuale(cartella=None, embedding_function=EmbeddingFinto())


@pytest.fixture(autouse=True)
def grafici_temporanei(tmp_path, monkeypatch):
    import grafici
    monkeypatch.setattr(grafici, "CHART_DIR", tmp_path)
    monkeypatch.setattr(config, "CHART_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def database_temporanei(tmp_path, monkeypatch):
    """Archivio SQLite e base DuckDB dei test in una cartella temporanea, mai accanto al codice."""
    monkeypatch.setattr(config, "ARCHIVIO_DB", tmp_path / "archivio.sqlite")
    monkeypatch.setattr(config, "ANALITICO_DB", tmp_path / "analitico.duckdb")
    return tmp_path
