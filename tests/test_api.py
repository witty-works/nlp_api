from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_read_main():
    response = client.get("/", allow_redirects=False)
    assert response.status_code == 301

def test_read_form():
    response = client.get("/form")
    assert response.status_code == 200

def test_api():
    request_data = {"text": "Wir suchen Ninja Rockstar Programmierer für unsere Kunden"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Kunden",
            "category": "gendered_denominations",
            "start": 51,
            "end": 57,
            "alternatives": ["Kund:innen", "Kundinnen und Kunden", "Kundschaft "],
            "label": "Geschlechtsspezifische Bezeichnungen",
            "reason": "Diese Bezeichnung ist männlich konnotiert, auch wenn sie sprachlich neutral ist. Aufgrund einer hohen Repräsentation von (weißen) Männern in der Branche entstehen bei diesem Begriff vor allem Bilder von Männern vor dem inneren Auge. Dadurch wird Menschen mit unterschiedlichem Hintergrund das Gefühl vermittelt, dass sie nicht in diese Branche gehören.",
            "solution": "Um ein inklusives Bild zu provozieren, sollten Sie in Ihrer Formulierung nicht nur sprachlich, sondern auch mental neutral sein, indem Sie die verschiedenen Geschlechter ausdrücklich erwähnen oder durch geschlechtslose Worte ersetzen."
        },
        {
            "text": "Ninja",
            "category": "boasting_words",
            "start": 11,
            "end": 16,
            "alternatives": ["jemand, der erfahren und fachkundig ist","jemand mit Know-how und Ausdauer","Mensch, der seine Fachkenntnis ständig vertieft"],
            "label": "Superlative Wörter",
            "reason": "Mit diesem Begriff nutzen Sie die Sprache der Superlative - oder auch Prahlerei - genannt. Superlative Begriffe in der Beschreibung der Firma schrecken viele Bewerber:innen ab, da bei ihnen unbewusst die Empfindung entsteht, im Sinne der Superlative mithalten und so sein zu müssen.",
            "solution": "Es wird dringend empfohlen, solche Begriffe zu vermeiden."
        },
        {
            "text": "Rockstar",
            "category": "boasting_words",
            "start": 17,
            "end": 25,
            "alternatives": ['jemand, der Meilensteine erreichen will','strebsam','fleißig','jemand, der mit dem Team gemeinsame Ziele verfolgt','du willst mit dem Team etwas erreichen','zielorientierter Mensch','tatkräftige Person','Tatmensch','jemand, der unternehmerisch denkt','jemand, der Ziele mit Elan verfolgt'],
            "label": "Superlative Wörter",
            "reason": "Mit diesem Begriff nutzen Sie die Sprache der Superlative - oder auch Prahlerei - genannt. Superlative Begriffe in der Beschreibung der Firma schrecken viele Bewerber:innen ab, da bei ihnen unbewusst die Empfindung entsteht, im Sinne der Superlative mithalten und so sein zu müssen.",
            "solution": "Es wird dringend empfohlen, solche Begriffe zu vermeiden."
        }
    ]
"""
def test_api_grammatic():

    request_data = {"text": "Die Deutsche Bahn als Partner im öffentlichen Personennahverkehr"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Die Deutsche Bahn als Partner",
            "category": "grammatic",
            "start": 0,
            "end": 29,
            "alternatives": "Die Deutsche Bahn als Partnerin"
        }
    ]
"""
def test_api_english():
    request_data = {"text": "We are searching for analytical ninja rockstar programmer for our customers"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == [
        {
            "start": 21,
            "end": 31,
            "category": "male_coded_terms",
            "alternatives": [],
            "text": "analytical",
            "label": "Männlich konnotierte Begriffe",
            "reason": "Dieser Begriff ist männlich konnotiert. Frauen werden sich durch dieses Wort unbewusst abgeschreckt fühlen. Dadurch fällt die Wahrscheinlichkeit, dass sich Frauen bewerben.",
            "solution": "Verwenden Sie eine der vorgeschlagenen Alternativen. Oder schreiben Sie es selbst um, so dass es teamorientierter, weniger wettbewerbsfähig klingt und auf den Sinn in der Arbeit Bezug nimmt."
        }
    ]

def test_api_response_lang():
    request_data = {"text": "Wir suchen Ninja Rockstar Programmierer für unsere Kunden", "response_lang": "en_GB"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Kunden",
            "category": "gendered_denominations",
            "start": 51,
            "end": 57,
            "alternatives": ["Kund:innen", "Kundinnen und Kunden", "Kundschaft "],
            "label": "Gendered Denominations",
            "reason": "This denomination is male coded, even if linguistically it is neutral. Because of a high representation of (white) men in the field, the inner eye unconsciously produces males behind this term. Thereby making people with diverse background feel that they will not be able to belong in this setting.",
            "solution": "In order to provoke an inclusive image, be not only linguistically, but also mentally neutral in your formulation by explicitly mentioning the different genders or being truly gender neutral by more general words."
        },
        {
            "text": "Ninja",
            "category": "boasting_words",
            "start": 11,
            "end": 16,
            "alternatives": ["jemand, der erfahren und fachkundig ist","jemand mit Know-how und Ausdauer","Mensch, der seine Fachkenntnis ständig vertieft"],
            "label": "Superlative Wörter",
            "reason": "With this term you make use of superlative - or also called  boasting - language. Superlative terms in the description of a company discourage many applicants, since because such language unconsciously provokes the feeling within candidates that they will have to comply with and be like the superlatives.",
            "solution": "It is highly recommended to avoid such terms."
        },
        {
            "text": "Rockstar",
            "category": "boasting_words",
            "start": 17,
            "end": 25,
            "alternatives": ['jemand, der Meilensteine erreichen will','strebsam','fleißig','jemand, der mit dem Team gemeinsame Ziele verfolgt','du willst mit dem Team etwas erreichen','zielorientierter Mensch','tatkräftige Person','Tatmensch','jemand, der unternehmerisch denkt','jemand, der Ziele mit Elan verfolgt'],
            "label": "Superlative Wörter",
            "reason": "With this term you make use of superlative - or also called  boasting - language. Superlative terms in the description of a company discourage many applicants, since because such language unconsciously provokes the feeling within candidates that they will have to comply with and be like the superlatives.",
            "solution": "It is highly recommended to avoid such terms."
        }
    ]

def test_api_false_positive():
    request_data = {"text": "Greenpeace is an international company with headquarters in London."}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == []

def test_api_missing_response_lang():
    request_data = {"text": "Greenpeace is an international company with headquarters in London.", "response_lang": "es_ES"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 400

def test_api_missing_data():
    response = client.post("/check")
    assert response.status_code == 422

def test_api_empty_data():
    request_data = {}

    response = client.post("/check", json=request_data)
    assert response.status_code == 422

def test_language_detection_german():
    request_data = {"text": "Greenpeace ist eine internationale Firma mit Hauptquartier in London."}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"

def test_language_detection_fail():
    request_data = {"text": "Voila", "lang": "es"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 400
