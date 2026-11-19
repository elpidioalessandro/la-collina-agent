#!/usr/bin/env bash
# La Collina: installa ciò che manca e avvia i tre servizi in un solo terminale.
#
#   ./start.sh         agente dati (8000) + back end (3001) + front end (5173); Ctrl+C li ferma tutti
#   ./start.sh test    test di agente dati e back end, più la build del front end (non chiamano Groq)
#
# Funziona con la bash di macOS (3.2) e su Linux. Serve: Python ≥ 3.12, Node.js ≥ 20.
set -euo pipefail
cd "$(dirname "$0")"

errore() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
info() { printf '\033[2m· %s\033[0m\n' "$*"; }
ok() { printf '\033[32m✓ %s\033[0m\n' "$*"; }

trova_python() {
  for p in python3.13 python3.12 python3; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
      PYTHON="$p"
      return
    fi
  done
  errore "Serve Python 3.12 o più recente (python3 --version)."
}

controlla_node() {
  command -v node >/dev/null 2>&1 || errore "Serve Node.js 20 o più recente: https://nodejs.org"
  node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' \
    || errore "Serve Node.js 20 o più recente (ora: $(node --version))."
}

prepara_python() {
  if [ ! -x data_agent/.venv/bin/python ]; then
    info "Creo l'ambiente Python in data_agent/.venv"
    "$PYTHON" -m venv data_agent/.venv
  fi
  # Reinstalla solo se requirements.txt è cambiato dall'ultima installazione.
  if ! cmp -s data_agent/requirements.txt data_agent/.venv/.requisiti-installati; then
    info "Installo le dipendenze Python (la prima volta qualche minuto)"
    data_agent/.venv/bin/pip install -q --upgrade pip
    data_agent/.venv/bin/pip install -q -r data_agent/requirements.txt
    cp data_agent/requirements.txt data_agent/.venv/.requisiti-installati
  fi
}

prepara_node() {
  local cartella="$1"
  if [ ! -d "$cartella/node_modules" ] || [ "$cartella/package-lock.json" -nt "$cartella/node_modules/.package-lock.json" ]; then
    info "Installo le dipendenze di $cartella"
    (cd "$cartella" && npm ci --silent --no-audit --no-fund)
  fi
}

valore_env() {
  # Legge una variabile dal .env senza eseguirlo.
  sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1 | tr -d '"'"'"'\r'
}

controlla_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    errore "Ho creato .env da .env.example: inserisci la tua GROQ_API_KEY (https://console.groq.com/keys) e rilancia ./start.sh"
  fi
  local chiave
  chiave="$(valore_env GROQ_API_KEY)"
  if [ -z "$chiave" ] || [ "$chiave" = "la_tua_chiave_groq" ]; then
    errore "Nel file .env manca la GROQ_API_KEY: inseriscila e rilancia ./start.sh"
  fi
}

controlla_porta() {
  if command -v lsof >/dev/null 2>&1 && lsof -ti ":$1" >/dev/null 2>&1; then
    errore "La porta $1 è già occupata. Chiudi il servizio che la usa: lsof -ti :$1 | xargs kill"
  fi
}

con_prefisso() {
  local nome="$1"
  while IFS= read -r riga; do printf '%s %s\n' "$nome" "$riga"; done
}

attendi() {
  # attendi URL secondi descrizione servizi_attesi: aspetta che l'URL risponda; si ferma subito se un servizio muore.
  local i=0
  until curl -fsS "$1" >/dev/null 2>&1; do
    [ "$(jobs -r | wc -l)" -lt "$4" ] && errore "$3 si è fermato all'avvio: guarda i messaggi qui sopra."
    i=$((i + 1))
    [ "$i" -ge "$2" ] && errore "$3 non risponde dopo $2 secondi: guarda i messaggi qui sopra."
    sleep 1
  done
}

esegui_test() {
  info "Test dell'agente dati"
  (cd data_agent && .venv/bin/python -m pytest -q)
  info "Test del back end"
  (cd backend && npm test --silent)
  info "Build del front end"
  (cd frontend && npm run build --silent >/dev/null)
  ok "Tutto verde"
}

avvia() {
  controlla_env
  local porta_dati porta_backend
  porta_dati="$(valore_env DATA_AGENT_PORT)"; porta_dati="${porta_dati:-8000}"
  porta_backend="$(valore_env BACKEND_PORT)"; porta_backend="${porta_backend:-3001}"
  for porta in "$porta_dati" "$porta_backend" 5173; do controlla_porta "$porta"; done

  # Ctrl+C (o un servizio che si ferma) chiude tutti i processi avviati da questo script.
  trap 'trap - INT TERM EXIT; printf "\n"; info "Fermo i servizi"; pkill -P $$ 2>/dev/null; wait 2>/dev/null' EXIT
  trap 'exit 130' INT TERM

  info "Avvio l'agente dati (la prima volta scarica il modello di embedding multilingue, circa 135 MB)"
  (cd data_agent && PYTHONUNBUFFERED=1 exec .venv/bin/python api.py) 2>&1 | con_prefisso "[dati]   " &
  attendi "http://127.0.0.1:$porta_dati/salute" 300 "L'agente dati" 1
  ok "Agente dati su http://127.0.0.1:$porta_dati"

  (cd backend && exec node src/server.js) 2>&1 | con_prefisso "[backend]" &
  attendi "http://127.0.0.1:$porta_backend/api/health" 30 "Il back end" 2
  ok "Back end su http://localhost:$porta_backend"

  (cd frontend && exec node_modules/.bin/vite --strictPort) 2>&1 | con_prefisso "[web]    " &
  attendi "http://localhost:5173" 30 "Il front end" 3
  ok "Apri http://localhost:5173 · Ctrl+C per fermare tutto"

  # Resta in ascolto finché un servizio non si ferma (o Ctrl+C).
  while [ "$(jobs -r | wc -l)" -ge 3 ]; do sleep 2; done
  errore "Un servizio si è fermato: guarda i messaggi qui sopra."
}

trova_python
controlla_node
command -v curl >/dev/null 2>&1 || errore "Serve curl."
prepara_python
prepara_node backend
prepara_node frontend

case "${1:-avvia}" in
  test) esegui_test ;;
  avvia) avvia ;;
  *) errore "Uso: ./start.sh [test]" ;;
esac
