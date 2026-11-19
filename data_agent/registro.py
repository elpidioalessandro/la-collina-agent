"""Log strutturati dell'agente dati: una riga per evento, con campi chiave=valore (o JSON con LOG_FORMAT=json).

Ogni riga porta l'id della richiesta, così le righe di una stessa domanda si ritrovano anche quando
più domande arrivano insieme."""
import contextvars
import json
import logging
import os
import sys

ID_RICHIESTA: contextvars.ContextVar[str] = contextvars.ContextVar("id_richiesta", default="-")
_CAMPI_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "id"}


class _AggiungiId(logging.Filter):
    def filter(self, record):
        record.id = ID_RICHIESTA.get()
        return True


def _campi(record) -> dict:
    return {k: v for k, v in vars(record).items() if k not in _CAMPI_STANDARD}


def _valore(v) -> str:
    testo = str(v)
    if not testo or any(c in testo for c in ' "='):
        return '"' + testo.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return testo


class FormatoChiaveValore(logging.Formatter):
    """2026-11-19 15:02:11 INFO analizza id=3f2a9c1b durata_s=12.4 strumenti=resi+crea_grafico ..."""

    def format(self, record):
        riga = [self.formatTime(record, "%Y-%m-%d %H:%M:%S"), record.levelname, record.getMessage()]
        if record.id != "-":  # gli eventi fuori da una richiesta (avvio, ricarica) non hanno id
            riga.append(f"id={record.id}")
        riga += [f"{k}={_valore(v)}" for k, v in _campi(record).items()]
        testo = " ".join(riga)
        if record.exc_info:
            testo += "\n" + self.formatException(record.exc_info)
        return testo


class FormatoJson(logging.Formatter):
    def format(self, record):
        voce = {"ora": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "livello": record.levelname,
                "evento": record.getMessage(), "id": record.id, **_campi(record)}
        if record.exc_info:
            voce["eccezione"] = self.formatException(record.exc_info)
        return json.dumps(voce, ensure_ascii=False, default=str)


def configura(livello: str | None = None, formato: str | None = None) -> logging.Logger:
    """Configura il logger "la_collina" (livello da LOG_LEVEL, formato da LOG_FORMAT: testo o json)."""
    registro = logging.getLogger("la_collina")
    registro.setLevel((livello or os.getenv("LOG_LEVEL") or "INFO").upper())
    registro.propagate = False
    for vecchio in list(registro.handlers):
        registro.removeHandler(vecchio)
    gestore = logging.StreamHandler(sys.stdout)
    gestore.addFilter(_AggiungiId())
    usa_json = (formato or os.getenv("LOG_FORMAT") or "testo").lower() == "json"
    gestore.setFormatter(FormatoJson() if usa_json else FormatoChiaveValore())
    registro.addHandler(gestore)
    return registro


def registro(nome: str) -> logging.Logger:
    return logging.getLogger(f"la_collina.{nome}")
