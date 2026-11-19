import strumenti


def test_codice_pandas_errore_poi_corretto(dati):
    strumenti.nuova_domanda(dati)
    errore = strumenti.esegui_codice_pandas.invoke({"codice": "risultato = vendite['brandd'].nunique()"})
    assert errore.startswith("ERRORE nel codice (tentativo 1/3)")
    ok = strumenti.esegui_codice_pandas.invoke({"codice": "risultato = vendite['brand'].nunique()"})
    assert ok == "10"


def test_codice_pandas_limite_tentativi(dati):
    strumenti.nuova_domanda(dati)
    for _ in range(3):
        strumenti.esegui_codice_pandas.invoke({"codice": "1/0"})
    assert "limite di tentativi" in strumenti.esegui_codice_pandas.invoke({"codice": "risultato = 1"})


def test_grafici_salvati(dati, grafici_temporanei):
    stato = strumenti.nuova_domanda(dati)
    strumenti.crea_grafico.invoke({"metrica": "incasso", "raggruppa_per": "anno"})
    strumenti.esegui_codice_pandas.invoke({"codice": "plt.plot([1, 2, 3])\nrisultato = 'ok'"})
    assert len(stato.grafici) == 2
    assert all((grafici_temporanei / n).is_file() for n in stato.grafici)


def test_errore_leggibile_per_l_agente(dati):
    strumenti.nuova_domanda(dati)
    assert strumenti.resi.invoke({"brand": "Gucci"}).startswith("ERRORE: Nessun dato per brand")


def test_due_domande_in_parallelo_non_si_mescolano(dati, grafici_temporanei):
    """Ogni domanda ha il suo stato: grafici e tentativi di codice non passano da un thread all'altro."""
    import threading

    partenza = threading.Barrier(2)
    esiti = {}

    def domanda(nome, metrica):
        stato = strumenti.nuova_domanda(dati)
        partenza.wait()
        strumenti.crea_grafico.invoke({"metrica": metrica, "raggruppa_per": "brand"})
        strumenti.esegui_codice_pandas.invoke({"codice": "plt.plot([1, 2])\nrisultato = 'ok'"})
        strumenti.esegui_codice_pandas.invoke({"codice": "1/0"})
        esiti[nome] = stato

    fili = [threading.Thread(target=domanda, args=("a", "resi")), threading.Thread(target=domanda, args=("b", "incasso"))]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    a, b = esiti["a"], esiti["b"]
    assert len(a.grafici) == 2 and len(b.grafici) == 2
    assert not set(a.grafici) & set(b.grafici)
    assert a.tentativi_codice == 2 and b.tentativi_codice == 2


def test_strumento_senza_domanda_aperta():
    import contextvars

    import pytest

    with pytest.raises(RuntimeError, match="Nessuna domanda in corso"):
        contextvars.Context().run(strumenti.stato_corrente)


def test_grafici_vecchi_cancellati(grafici_temporanei):
    import os
    import time

    import grafici

    vecchio, nuovo = grafici_temporanei / "aaaaaaaaaaaa.png", grafici_temporanei / "bbbbbbbbbbbb.png"
    for f in (vecchio, nuovo):
        f.write_bytes(b"\x89PNG")
    due_giorni_fa = time.time() - 48 * 3600
    os.utime(vecchio, (due_giorni_fa, due_giorni_fa))
    assert grafici.pulisci_vecchi(max_ore=24) == 1
    assert not vecchio.exists() and nuovo.exists()
