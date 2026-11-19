import pytest

DOMANDE = {
    "Una cliente vuole cambiare un capo preso in saldo: si può?": "SEZ 5.5",
    "Senza scontrino posso fare il cambio?": "SEZ 5.4",
    "Posso fare il 10% a un cliente abituale? Si somma ai saldi?": "SEZ 4.2",
    "Capo difettoso dopo un mese: cosa faccio?": "SEZ 6.4",
    "Lardoni veste piccolo? Che taglia consiglio?": "SEZ 2.2",
    "La taglia mancante si può ordinare?": "SEZ 2.4",
    "Un cliente ha un buono da 100 euro e spende 60, cosa succede?": "SEZ 5.9",
    "Come funzionano le domeniche?": "SEZ 7.5",
    "Un profumo aperto si può cambiare?": "SEZ 5.6",
    "Cosa succede alla merce a fine stagione?": "SEZ 9.1",
    "A che ora apre il negozio il lunedì?": "SEZ 1.2",
    "Quali regole sugli sconti possono essere violate?": "SEZ 10.3",
}


def test_sezioni_lette(manuale):
    assert len(manuale.sezioni) == 54
    assert manuale.sezioni[0]["parte"].startswith("PARTE 1")


@pytest.mark.parametrize("domanda,attesa", DOMANDE.items())
def test_sezione_giusta_tra_le_prime_4(manuale, domanda, attesa):
    assert attesa in [r["codice"] for r in manuale.cerca(domanda, 4)]


def test_domande_di_valutazione_valide(manuale):
    """Le sezioni attese in valutazione/domande_rag.csv esistono tutte, e i due gruppi sono bilanciati."""
    import valuta_rag

    domande = valuta_rag.leggi_domande()
    assert {d["tipo"] for d in domande} == {"parole del manuale", "sinonimi"}
    assert all(s in manuale.per_id for d in domande for s in d["attese"])
    gruppi = [d["tipo"] for d in domande]
    assert abs(gruppi.count("sinonimi") - gruppi.count("parole del manuale")) <= 2


def test_valutazione_rag_gira(manuale):
    """Lo script di valutazione produce la tabella (qui con l'embedding finto: i numeri veri li dà il README)."""
    import valuta_rag

    domande = valuta_rag.leggi_domande()
    esiti = valuta_rag.misura({"inglese": manuale, "multilingue": manuale}, domande[:3] + domande[-3:])
    tabella = valuta_rag.tabella(esiti)
    assert tabella.splitlines()[0].startswith("| Configurazione |") and len(tabella.splitlines()) == 7
    assert esiti["solo parole (BM25)"]["tutte"]["n"] == 6
