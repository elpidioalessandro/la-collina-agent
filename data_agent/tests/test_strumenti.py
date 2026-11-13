import strumenti


def test_codice_pandas_errore_poi_corretto(dati):
    strumenti.imposta_dati(dati)
    strumenti.nuova_domanda()
    errore = strumenti.esegui_codice_pandas.invoke({"codice": "risultato = vendite['brandd'].nunique()"})
    assert errore.startswith("ERRORE nel codice (tentativo 1/3)")
    ok = strumenti.esegui_codice_pandas.invoke({"codice": "risultato = vendite['brand'].nunique()"})
    assert ok == "10"


def test_codice_pandas_limite_tentativi(dati):
    strumenti.imposta_dati(dati)
    strumenti.nuova_domanda()
    for _ in range(3):
        strumenti.esegui_codice_pandas.invoke({"codice": "1/0"})
    assert "limite di tentativi" in strumenti.esegui_codice_pandas.invoke({"codice": "risultato = 1"})


def test_grafici_salvati(dati, grafici_temporanei):
    strumenti.imposta_dati(dati)
    strumenti.nuova_domanda()
    strumenti.crea_grafico.invoke({"metrica": "incasso", "raggruppa_per": "anno"})
    strumenti.esegui_codice_pandas.invoke({"codice": "plt.plot([1, 2, 3])\nrisultato = 'ok'"})
    assert len(strumenti.STATO["grafici"]) == 2
    assert all((grafici_temporanei / n).is_file() for n in strumenti.STATO["grafici"])


def test_errore_leggibile_per_l_agente(dati):
    strumenti.imposta_dati(dati)
    assert strumenti.resi.invoke({"brand": "Gucci"}).startswith("ERRORE: Nessun dato per brand")
