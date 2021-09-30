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
        "category": "gendered_roles",
        "start": 51,
        "end": 57,
        "alternatives": [
            "Kundschaft",
            "Kund:innen",
            "Kundinnen und Kunden"
        ],
        "label": "Geschlechtsspezifische Rollen",
        "reason": "Das männliche Generikum spricht nicht alle Geschlechter oder Geschlechtsidentitäten an. Viele Menschen fühlen sich daher nicht in den Dialog einbezogen.",
        "solution": "Verwenden Sie eine Schreibweise, die das weibliche Geschlecht sowie auch andere Geschlechteridentitäten, die nicht einem binären Verständnis von Geschlecht folgen, anspricht."
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

def test_api_orthpgraphy():
    request_data = {"text": "Halo, siehst du die schnellen Hund!!!"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
        "text": "Halo",
        "category": "empty_words",
        "start": 0,
        "end": 4,
        "alternatives": [
            "Hallo"
        ],
        "label": "Mögliche Wortverwechslung: ",
        "reason": "Korrigieren sie eventuelle Rechtschreib- oder Grammatikfehler, um die Wirkung ihrer Texte zu maximieren.",
        "solution": "Meinten Sie die Begrüßung „Hallo“? Ein Halo ist ein Lichteffekt."
        },
        {
        "text": "die schnellen Hund",
        "category": "empty_words",
        "start": 16,
        "end": 34,
        "alternatives": [
            "den schnellen Hund",
            "dem schnellen Hund",
            "der schnelle Hund"
        ],
        "label": "Evtl. keine Übereinstimmung von Kasus, Numerus oder Genus",
        "reason": "Korrigieren sie eventuelle Rechtschreib- oder Grammatikfehler, um die Wirkung ihrer Texte zu maximieren.",
        "solution": "Möglicherweise fehlende grammatische Übereinstimmung von Kasus, Numerus oder Genus. Beispiel: ‚mein kleiner Haus‘ statt ‚mein kleines Haus‘"
        },
        {
        "text": "!!!",
        "category": "empty_words",
        "start": 34,
        "end": 37,
        "alternatives": [
            "!"
        ],
        "label": "",
        "reason": "Korrigieren sie eventuelle Rechtschreib- oder Grammatikfehler, um die Wirkung ihrer Texte zu maximieren.",
        "solution": "Die Verwendung von mehreren Frage- oder Ausrufezeichen wirkt oft übertrieben emphatisch."
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
        "label": "Agentic Language",
        "reason": "This term is agentic, describing attributes that enforce the male stereotype as the the norm. People not falling into that stereotype (women but also other underrepresented groups) will feel unconsciously excluded by this word. ",
        "solution": "Use a word combination that sounds more team-oriented and refers to the purpose in work."
        }
    ]

def test_api_corporate_rule():
    request_data = {"text": "Kund/in"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
        "text": "/in",
        "category": "empty_words",
        "start": 4,
        "end": 7,
        "alternatives": [
            ":in"
        ],
        "label": "Firmenrichtlinie",
        "reason": "Bei der Deutschen Bahn verwenden wir den Doppelpunkt, um geschlechter inklusiv zu schreiben, anstelle von \"*\", \"_\" oder \"/\".",
        "solution": "Bitte verwenden Sie den Doppelpunkt, um geschlechter inklusive zu schreiben."
        }
    ]

def test_api_false_positive():
    request_data = {"text": "Greenpeace is an international company with headquarters in London."}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == []

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
