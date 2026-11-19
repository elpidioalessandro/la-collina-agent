.PHONY: dev test

# make dev: installa ciò che manca e avvia i tre servizi (equivale a ./start.sh)
dev:
	./start.sh

# make test: test di agente dati e back end, build del front end
test:
	./start.sh test
