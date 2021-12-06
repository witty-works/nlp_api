from fastapi.applications import FastAPI
from fastapi.testclient import TestClient
from app.main import app
from app.main import redis, set_rules
import json
from app.models import RequestIn

client = TestClient(app)


def test_categories():
    response = client.get("/categories")
    assert response.status_code == 200

    first_record = response.json()

    assert "hollow" in first_record


def test_api_corporate_false_positives():
    request_data = {
        "text": "Die Bahn ist stark wegen ihrer Führungskräfte!",
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
