from fastapi.applications import FastAPI
from fastapi.testclient import TestClient
from app.main import app
from app.main import redis, set_rules
import json
from app.models import RequestIn

client = TestClient(app)


def test_read_main():
    response = client.get("/", allow_redirects=False)
    assert response.status_code == 301


def test_read_form():
    response = client.get("/form")
    assert response.status_code == 200


def test_api():
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {"store_context": False},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Kunden",
            "context": "",
            "category": "gendered",
            "subcategory": "titles",
            "start": 42,
            "end": 48,
            "alternatives": [
                "Auftraggebende",
                "Bestellende, Kund:innen",
                "Kundschaft",
                "Klientel, beziehende Personen",
                "Personen, die (…) kaufen",
                "Beauftragende Firmen",
            ],
            "label": "Geschlechtsspezifisch: Titel",
            "reason": "Das männliche Generikum spricht nicht alle Geschlechter oder Geschlechtsidentitäten an. Viele Menschen fühlen sich daher nicht in den Dialog einbezogen.",
            "solution": "Verwenden Sie eine Schreibweise, die das weibliche Geschlecht sowie auch andere Geschlechteridentitäten, die nicht einem binären Verständnis von Geschlecht folgen, anspricht.",
        },
        {
            "text": "Ninja",
            "context": "",
            "category": "style",
            "subcategory": "exaggerating",
            "start": 11,
            "end": 16,
            "alternatives": [
                "Jemand, der erfahren und fachkundig ist",
                "Jemand mit Know-how und Ausdauer",
                "Mensch, der seine Fachkenntnis ständig vertieft",
            ],
            "label": "Stil: Superlative",
            "reason": "Kommuniziert, dass sich Menschen sich im Sinne der Superlative anpassen müssen.",
            "solution": "Verwenden Sie eine authentisch und ehrlich klingende Aussage.",
        },
    ]


def test_api_gendered_subcategories():
    request_data = {
        "text": "Ich bin hier der Manager und dein Boss!",
        "config": {"store_context": False},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Manager",
            "context": "",
            "category": "gendered",
            "subcategory": "function",
            "start": 17,
            "end": 24,
            "alternatives": ["Management, Manager:in"],
            "label": "Geschlechtsspezifisch: Spezielle Funktionen",
            "reason": "Aus wirtschaftlich-historischen Gründen wird unbewusst ein Bild eines Mannes vor dem inneren Auge hervorgerufen. Das weibliche Geschlecht oder andere Geschlechtsidentitäten werden nicht sichtbar. Und sie fühlen sich nicht zugehörig.",
            "solution": "Umgehen Sie mit anderen Worten das unbewusst hervorgerufene Bild. Nutzen Sie eher das Nomen, das die Tätigkeit bezeichnet, um das unbewusste Bild zu umgehen. Oder verwenden Sie eine geschlechtsneutrale Bezeichnung.",
        },
        {
            "text": "der",
            "context": "",
            "category": "gendered",
            "subcategory": "function",
            "start": 13,
            "end": 16,
            "alternatives": ["der:die"],
            "label": "Geschlechtsspezifisch: Spezielle Funktionen",
            "reason": "Aus wirtschaftlich-historischen Gründen wird unbewusst ein Bild eines Mannes vor dem inneren Auge hervorgerufen. Das weibliche Geschlecht oder andere Geschlechtsidentitäten werden nicht sichtbar. Und sie fühlen sich nicht zugehörig.",
            "solution": "Umgehen Sie mit anderen Worten das unbewusst hervorgerufene Bild. Nutzen Sie eher das Nomen, das die Tätigkeit bezeichnet, um das unbewusste Bild zu umgehen. Oder verwenden Sie eine geschlechtsneutrale Bezeichnung.",
        },
        {
            "text": "Boss",
            "context": "",
            "category": "gendered",
            "subcategory": "leadership",
            "start": 34,
            "end": 38,
            "alternatives": [
                "Leitende Kraft",
                "Leitungsperson, Leitung, Vorgesetzte:r",
                "Leitende Kräfte",
                "Leitungskräfte",
                "Leitungspersonen",
                "Vorgesetzte, entscheidungsbefugte Person",
                "Verantwortliche Person",
            ],
            "label": "Geschlechtsspezifisch: Führungsstereotyp",
            "reason": "Besetzt das Thema der Führung stereotyp männlich und traditionell hierarchisch.",
            "solution": "Verwenden Sie Begriffe, die von einer unterstützenden Vorstellung der Führung ausgeht und verschiedene Geschlechter meinen kann.",
        },
    ]


def test_api_context():
    request_data = {"text": "Wir suchen Kunden"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Kunden",
            "context": "Wir suchen Kunden",
            "category": "gendered",
            "subcategory": "titles",
            "start": 11,
            "end": 17,
            "alternatives": [
                "Auftraggebende",
                "Bestellende, Kund:innen",
                "Kundschaft",
                "Klientel, beziehende Personen",
                "Personen, die (…) kaufen",
                "Beauftragende Firmen",
            ],
            "label": "Geschlechtsspezifisch: Titel",
            "reason": "Das männliche Generikum spricht nicht alle Geschlechter oder Geschlechtsidentitäten an. Viele Menschen fühlen sich daher nicht in den Dialog einbezogen.",
            "solution": "Verwenden Sie eine Schreibweise, die das weibliche Geschlecht sowie auch andere Geschlechteridentitäten, die nicht einem binären Verständnis von Geschlecht folgen, anspricht.",
        }
    ]


def test_api_disabled_categories():
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {
            "store_context": False,
            "disabled_categories": "exaggerating,hollow",
        },
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Kunden",
            "context": "",
            "category": "gendered",
            "subcategory": "titles",
            "start": 42,
            "end": 48,
            "alternatives": [
                "Auftraggebende",
                "Bestellende, Kund:innen",
                "Kundschaft",
                "Klientel, beziehende Personen",
                "Personen, die (…) kaufen",
                "Beauftragende Firmen",
            ],
            "label": "Geschlechtsspezifisch: Titel",
            "reason": "Das männliche Generikum spricht nicht alle Geschlechter oder Geschlechtsidentitäten an. Viele Menschen fühlen sich daher nicht in den Dialog einbezogen.",
            "solution": "Verwenden Sie eine Schreibweise, die das weibliche Geschlecht sowie auch andere Geschlechteridentitäten, die nicht einem binären Verständnis von Geschlecht folgen, anspricht.",
        }
    ]


def test_api_gender_endings():
    request_data = {
        "text": "Hallo Kunde. Wir geben unseren Kunden alles.",
        "config": {"store_context": False, "german_gender_ending": "*in"},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "Kunde",
            "context": "",
            "category": "gendered",
            "subcategory": "titles",
            "start": 6,
            "end": 11,
            "alternatives": [
                "Kund*in",
                "Kundschaft",
                "Klientel, Auftraggebende",
                "Bestellende, beziehende Person",
                "Person, die (…) kauft",
                "Beauftragende Firma",
            ],
            "label": "Geschlechtsspezifisch: Titel",
            "reason": "Das männliche Generikum spricht nicht alle Geschlechter oder Geschlechtsidentitäten an. Viele Menschen fühlen sich daher nicht in den Dialog einbezogen.",
            "solution": "Verwenden Sie eine Schreibweise, die das weibliche Geschlecht sowie auch andere Geschlechteridentitäten, die nicht einem binären Verständnis von Geschlecht folgen, anspricht.",
        },
        {
            "text": "Kunden",
            "context": "",
            "category": "gendered",
            "subcategory": "titles",
            "start": 31,
            "end": 37,
            "alternatives": [
                "Auftraggebende",
                "Bestellende, Kund*innen",
                "Kundschaft",
                "Klientel, beziehende Personen",
                "Personen, die (…) kaufen",
                "Beauftragende Firmen",
            ],
            "label": "Geschlechtsspezifisch: Titel",
            "reason": "Das männliche Generikum spricht nicht alle Geschlechter oder Geschlechtsidentitäten an. Viele Menschen fühlen sich daher nicht in den Dialog einbezogen.",
            "solution": "Verwenden Sie eine Schreibweise, die das weibliche Geschlecht sowie auch andere Geschlechteridentitäten, die nicht einem binären Verständnis von Geschlecht folgen, anspricht.",
        },
    ]


def test_api_gender_endings_do_not_trigger_spellchecker():
    request_data = {
        "text": "Wie geht es dir? Bis du unser Matros/-in?",
        "config": {"store_context": False, "german_gender_ending": "/-in"},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == []


def test_api_orthography():
    request_data = {
        "text": "Ich gehe noch schnell ueber die Strasse!!!",
        "config": {"store_context": False},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "ueber",
            "context": "",
            "category": "orthography",
            "subcategory": "orthography",
            "start": 22,
            "end": 27,
            "alternatives": [
                "über",
                "Weber",
                "Leber",
                "Geber",
                "Heber",
                "Hueber",
                "aber",
                "unter",
                "neben",
                "Meter",
                "eher",
                "geben",
                "jeder",
                "leben",
                "neuer",
                "Peter",
                "jener",
                "weder",
                "Meer",
                "derer",
            ],
            "label": "Rechtschreibfehler",
            "reason": "Korrigieren sie eventuelle Rechtschreib- oder Grammatikfehler, um die Wirkung ihrer Texte zu maximieren.",
            "solution": "Möglicher Tippfehler gefunden.",
        },
        {
            "text": "Strasse",
            "context": "",
            "category": "orthography",
            "subcategory": "orthography",
            "start": 32,
            "end": 39,
            "alternatives": [
                "Straße",
                "Straßen",
                "Strauße",
                "Ostrasse",
                "Stresse",
                "Strapse",
                "Strass",
                "Trasse",
                "Straß",
                "Adresse",
                "Sträuße",
                "Krasse",
                "Straffe",
                "Strafe",
                "Strafte",
                "Zulasse",
                "Strauss",
                "Stramme",
                "Strauß",
                "Stanze",
            ],
            "label": "Rechtschreibfehler",
            "reason": "Korrigieren sie eventuelle Rechtschreib- oder Grammatikfehler, um die Wirkung ihrer Texte zu maximieren.",
            "solution": "Möglicher Tippfehler gefunden.",
        },
        {
            "text": "!!!",
            "context": "",
            "category": "orthography",
            "subcategory": "orthography",
            "start": 39,
            "end": 42,
            "alternatives": ["!"],
            "label": "",
            "reason": "Korrigieren sie eventuelle Rechtschreib- oder Grammatikfehler, um die Wirkung ihrer Texte zu maximieren.",
            "solution": "Die Verwendung von mehreren Frage- oder Ausrufezeichen wirkt oft übertrieben emphatisch.",
        },
    ]


def test_api_english():
    request_data = {
        "text": "We are searching for analytical ninja programmer for our customers",
        "config": {"store_context": False},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == [
        {
            "text": "analytical",
            "context": "",
            "category": "unconscious_bias",
            "subcategory": "agentic",
            "start": 21,
            "end": 31,
            "alternatives": [],
            "label": "Biased language: Agentic",
            "reason": "Unconsciously attributed to the male stereotype. Many do not feel attracted by these terms.",
            "solution": "Use team-oriented wording or referring to purpose.",
        }
    ]


def test_api_orthography_english():
    request_data = {"text": "I liki all the colors", "config": {"store_context": False}}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == [
        {
            "text": "liki",
            "context": "",
            "category": "orthography",
            "subcategory": "orthography",
            "start": 2,
            "end": 6,
            "alternatives": ["like", "wiki", "Loki", "Niki", "tiki", "Lili", "Kiki"],
            "label": "Spelling mistake",
            "reason": "Correct any spelling or grammatical errors to maximize the impact of their writing.",
            "solution": "Possible spelling mistake found.",
        },
        {
            "text": "colors",
            "context": "",
            "category": "orthography",
            "subcategory": "orthography",
            "start": 15,
            "end": 21,
            "alternatives": ["colours"],
            "label": "",
            "reason": "Correct any spelling or grammatical errors to maximize the impact of their writing.",
            "solution": "Possible spelling mistake. ‘colors’ is American English.",
        },
    ]


def test_api_gender_ending():
    request_data = {"text": "Kund/in", "config": {"store_context": False}}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == [
        {
            "text": "/in",
            "context": "",
            "category": "gendered",
            "subcategory": "gendered_denominations_ending",
            "start": 4,
            "end": 7,
            "alternatives": [":in"],
            "label": "Geschlechtsspezifisch: Inklusive Endung",
            "reason": "Konsistente Schreibweise ist vertrauenserweckender.",
            "solution": "Nutzen Sie den Genderstern oder -doppelpunkt, um durchgehend inklusiv zu sein.",
        }
    ]


def test_api_gender_ending_custom():
    request_data = {
        "text": "Kund/in",
        "config": {"store_context": False, "german_gender_ending": "/in"},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == []


def test_api_false_positive():
    request_data = {
        "text": "Greenpeace is an international company with headquarters in London.",
        "config": {"store_context": False},
    }

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
    request_data = {
        "text": "Greenpeace ist eine internationale Firma mit Hauptquartier in London.",
        "config": {"store_context": False},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"


def test_language_detection_fail():
    request_data = {"text": "Voila", "lang": "es"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 422


def test_log():
    request_data = {
        "text": "Voila",
        "context": "Voila",
        "lang": "auto",
        "id": "123",
        "start": 0,
        "end": 23,
        "type": "alternative",
        "details": {"text": "test"},
    }

    response = client.post("/log", json=request_data)
    assert response.status_code == 201


def test_categories():
    response = client.get("/categories")
    assert response.status_code == 200

    first_record = response.json()

    assert "hollow" in first_record


def test_api_corporate_false_positives():
    request_data = {
        "text": "Die Bahn ist stark auch wegen ihrer Führungskräfte!",
        "config": {"store_context": False},
    }

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "de"
    assert first_record["results"] == []


# test overwriting user configuration by company forced rules


def test_set_rules(event_loop):
    request_data = {
        "id": "test@gmail.com",
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {
            "store_context": True,
            "primary_language": "de-DE",
            "preferred_languages": "de",
            "preferred_variants": "de-DE",
            "german_gender_ending": "/in",
            "gendered_roles_format": "inclusive_gender",
        },
    }
    test_request = RequestIn(**request_data)

    company_object = {
        "users": ["test@gmail.com"],
        "config": {
            "forced": {
                "store_context": False,
                "primary_language": "en-GB",
                "preferred_languages": "en",
                "preferred_variants": "en-GB",
                "german_gender_ending": "In",
                "gendered_roles_format": "binary_gender",
            },
            "suggestion": {},
        },
    }

    # Set a value
    redis.set("test", json.dumps(company_object))
    event_loop.run_until_complete(set_rules(test_request))
    assert test_request.config.store_context == False
    assert test_request.config.primary_language == "en-GB"
    assert test_request.config.preferred_languages == "en"
    assert test_request.config.preferred_variants == "en-GB"
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test not overwriting user configuration by company suggestion/default rules


def test_set_rules_suggestion(event_loop):
    request_data = {
        "id": "test_default@gmail.com",
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {
            "store_context": True,
            "primary_language": "de-DE",
            "preferred_languages": "de",
            "preferred_variants": "de-DE",
            "german_gender_ending": "/in",
            "gendered_roles_format": "inclusive_gender",
        },
    }
    test_request = RequestIn(**request_data)

    company_object = {
        "users": ["test_default@gmail.com"],
        "config": {
            "suggestion": {
                "store_context": False,
                "primary_language": "en-GB",
                "preferred_languages": "en",
                "preferred_variants": "en-GB",
                "german_gender_ending": "In",
                "gendered_roles_format": "binary_gender",
            },
            "forced": {},
        },
    }

    # Set a value
    redis.set("test_default", json.dumps(company_object))
    test_result = event_loop.run_until_complete(set_rules(test_request))
    assert test_request.config.store_context == True
    assert test_request.config.primary_language == "de-DE"
    assert test_request.config.preferred_languages == "de"
    assert test_request.config.preferred_variants == "de-DE"
    assert test_request.config.german_gender_ending == "/in"
    assert test_request.config.gendered_roles_format == "inclusive_gender"


# test user not set any parameters, but company did


def test_set_company_rules(event_loop):
    request_data = {
        "id": "test@gmail.com",
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = RequestIn(**request_data)

    company_object = {
        "users": ["test@gmail.com"],
        "config": {
            "forced": {
                "store_context": False,
                "primary_language": "en-GB",
                "preferred_languages": "en",
                "preferred_variants": "en-GB",
                "german_gender_ending": None,
                "gendered_roles_format": "binary_gender",
            },
            "suggestion": {},
        },
    }

    # Set a value
    redis.set("test", json.dumps(company_object))
    event_loop.run_until_complete(set_rules(test_request))
    assert test_request.config.store_context == False
    assert test_request.config.primary_language == "en-GB"
    assert test_request.config.preferred_languages == "en"
    assert test_request.config.preferred_variants == "en-GB"
    # assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test user and company didn't set any rules


def test_set_default_rules(event_loop):
    request_data = {
        "id": "test_default@gmail.com",
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = RequestIn(**request_data)

    event_loop.run_until_complete(set_rules(test_request))
    assert test_request.config.store_context == True
    assert test_request.config.primary_language == "de-DE"
    assert test_request.config.preferred_languages == "de,en"
    assert test_request.config.preferred_variants == "de-DE,en-GB"
    assert test_request.config.german_gender_ending == ":in"
    assert test_request.config.gendered_roles_format == "inclusive_gender"


# test POST Redis endpoint


def test_store_rules():
    request_data = {
        "company": "TEST_COMPANY",
        "users": ["test@gmail.com"],
        "forced": {"gendered_roles_format": "binary_gender"},
        "suggestion": {"german_gender_ending": "In"},
    }
    response = client.post("/storeRules", json=request_data)
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert (
        response_content["config"]["forced"]["gendered_roles_format"] == "binary_gender"
    )
    assert response_content["config"]["suggestion"]["german_gender_ending"] == "In"
    assert (
        response_content["config"]["suggestion"]["preferred_variants"] == "de-DE,en-GB"
    )
