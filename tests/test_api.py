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
        "alternatives": [
            "Kund:innen",
            "Kundinnen und Kunden",
            "Kundschaft "
        ],
        "label": "Geschlechtsspezifische Bezeichnungen",
        "reason": "Aus wirtschaftlich-historischen Gründen wird unbewusst ein Bild eines Mannes vor dem inneren Auge hervorgerufen. Das weibliche Geschlecht oder andere Geschlechtsidentitäten werden also nicht sichtbar. Und sie fühlen sich nicht zugehörig. ",
        "solution": "Umgehen Sie mit anderen Worten das unbewusst hervorgerufene Bild. Nutzen Sie eher das Nomen, das die Tätigkeit bezeichnet, um das unbewusste Bild zu umgehen. Oder verwenden Sie eine geschlechtsneutrale Bezeichnung."
        },
        {
        "text": "Ninja",
        "category": "boasting_words",
        "start": 11,
        "end": 16,
        "alternatives": [
            "jemand, der erfahren und fachkundig ist",
            "jemand mit Know-how und Ausdauer",
            "Mensch, der seine Fachkenntnis ständig vertieft"
        ],
        "label": "Superlative Wörter",
        "reason": "Mit diesem Begriff nutzen Sie eine Sprache der Superlative. Viele Menschen empfinden dies als negativ, da der Eindruck entsteht, sich im Sinne der Superlative anpassen zu müssen.",
        "solution": "Verwenden Sie eine authentisch und ehrlich klingende Aussage."
        },
        {
        "text": "Rockstar",
        "category": "boasting_words",
        "start": 17,
        "end": 25,
        "alternatives": [
            "jemand, der Meilensteine erreichen will",
            "strebsam",
            "fleißig",
            "jemand, der mit dem Team gemeinsame Ziele verfolgt",
            "du willst mit dem Team etwas erreichen",
            "zielorientierter Mensch",
            "tatkräftige Person",
            "Tatmensch",
            "jemand, der unternehmerisch denkt",
            "jemand, der Ziele mit Elan verfolgt"
        ],
        "label": "Superlative Wörter",
        "reason": "Mit diesem Begriff nutzen Sie eine Sprache der Superlative. Viele Menschen empfinden dies als negativ, da der Eindruck entsteht, sich im Sinne der Superlative anpassen zu müssen.",
        "solution": "Verwenden Sie eine authentisch und ehrlich klingende Aussage."
        }
    ]

def test_api_english():
    request_data = {"text": "We are searching for analytical ninja rockstar programmer for our customers"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == [
        {
        "text": "analytical",
        "category": "agentic_language",
        "start": 21,
        "end": 31,
        "alternatives": [],
        "label": "Agentische Sprache",
        "reason": "Dieser Begriff ist agentisch und beschreibt Eigenschaften, die das männliche Stereotyp als Norm erklären. Menschen, die diesem Stereotyp nicht entsprechen (Frauen, sowie andere unterrepräsentierte Gruppen), fühlen sich durch dieses Wort unbewusst ausgeschlossen.",
        "solution": "Verwenden Sie eine Wortkombination, die teamorientierter klingt und auf den Sinn in der Arbeit Bezug nimmt."
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
        "alternatives": [
            "Kund:innen",
            "Kundinnen und Kunden",
            "Kundschaft "
        ],
        "label": "Gendered Denominations",
        "reason": "For economic-historical reasons, an image of a man is unconsciously evoked in front of the inner eye, even if the term is linguistically neutral. The female gender or other gender identities therefore do not become visible. And they will not feel to belong in this setting.",
        "solution": "In order to provoke an inclusive image, be not only linguistically, but also mentally neutral in your formulation. Rather use a noun that describes the activity. Or use a denomination that is truly gender-neutral."
        },
        {
        "text": "Ninja",
        "category": "boasting_words",
        "start": 11,
        "end": 16,
        "alternatives": [
            "jemand, der erfahren und fachkundig ist",
            "jemand mit Know-how und Ausdauer",
            "Mensch, der seine Fachkenntnis ständig vertieft"
        ],
        "label": "Boasting Words",
        "reason": "With this term you use a language of superlatives. Many people perceive this as negative, as it gives the impression of having to conform in terms of superlatives.",
        "solution": "Use an authentic and honest sounding statement."
        },
        {
        "text": "Rockstar",
        "category": "boasting_words",
        "start": 17,
        "end": 25,
        "alternatives": [
            "jemand, der Meilensteine erreichen will",
            "strebsam",
            "fleißig",
            "jemand, der mit dem Team gemeinsame Ziele verfolgt",
            "du willst mit dem Team etwas erreichen",
            "zielorientierter Mensch",
            "tatkräftige Person",
            "Tatmensch",
            "jemand, der unternehmerisch denkt",
            "jemand, der Ziele mit Elan verfolgt"
        ],
        "label": "Boasting Words",
        "reason": "With this term you use a language of superlatives. Many people perceive this as negative, as it gives the impression of having to conform in terms of superlatives.",
        "solution": "Use an authentic and honest sounding statement."
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
