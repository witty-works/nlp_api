import pytest
import logging
import json
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import Request
from app.main import (
    app,
    redis,
    fetch_configs_for_request,
)
from app.auth_service import (
    AuthError,
    __validate_scope,
    __get_token,
    __get_token_claims,
)
from app.models import (
    LangWithAutoType,
    RequestIn,
)

tokens = {
    "azureadbc_valid_expired": "eyJhbGciOiJSUzI1NiIsImtpZCI6IkN6d1lJSEUyNG5oRFNTdkhhT1pxaVNwTFV4UkFXZjluQ2kydEtnMXRCME0iLCJ0eXAiOiJKV1QifQ.eyJjdXJyZW50VGltZSI6MTY5NDU4OTkxMSwiZW1haWwiOiJsdWthcy5zbWl0aEB3aXR0eS53b3JrcyIsIm5hbWUiOiJmb28iLCJpZHAiOiJnb29nbGUuY29tIiwic3ViIjoiMjVlMDUwYTUtYTJmZC00MzZmLWE1YmUtM2I5NmZmZDAxOTU4Iiwib3RoZXJNYWlscyI6WyJsdWthcy5zbWl0aEB3aXR0eS53b3JrcyJdLCJleHRlbnNpb25fdGVybXNPZlVzZUNvbnNlbnREYXRlVGltZSI6MTY2Mjg5Mjk2OCwiZXh0ZW5zaW9uX01haWxpbmdDb25zZW50ZWQiOiJZZXMiLCJ0ZXJtc09mVXNlQ29uc2VudFJlcXVpcmVkIjpmYWxzZSwidGlkIjoiODE5MzJmZTEtZjI1ZS00M2ZjLWI2NzQtMDAyZmY4MjM1Mzg5Iiwic2NwIjoiYWNjZXNzX2FzX3VzZXIiLCJhenAiOiI3ZTA5MDMwOC01NzVhLTRlN2QtODRlNC03OGM4M2QwODNhYjYiLCJ2ZXIiOiIxLjAiLCJpYXQiOjE2OTQ1ODk5NjIsImF1ZCI6IjdlMDkwMzA4LTU3NWEtNGU3ZC04NGU0LTc4YzgzZDA4M2FiNiIsImV4cCI6MTY5NDY3NjM2MiwiaXNzIjoiaHR0cHM6Ly93aXR0eXdvcmtzZGV2LmIyY2xvZ2luLmNvbS84MTkzMmZlMS1mMjVlLTQzZmMtYjY3NC0wMDJmZjgyMzUzODkvdjIuMC8iLCJuYmYiOjE2OTQ1ODk5NjJ9.JtXTKr8pUEBQ5-hO1ak-L1IocXQdOW6rNaCS5DD1DAvt8ldo-n9APQVw8mqWlYmukrelqH48VwguYiCcD5-Lc8seWfX5lywXT4mnfsJscqGQr7iVL1s6GNBp2wsaRLNf6l8qzIVWa0UDREACdgUpJRmbvObILZa6z42E5ghOO9RxxVCsCKg6hwKKhtY2w6UEs1u26JF7BKHH7XFoX88CfG-kqVfhVw_zb_bOIhDrEGflWZzKdKx9LfaLS1VQjVY1I_IW1nL1EQaBo286MHpzLdxzeyLf6Jo9ASzgAeEqKD6v2PPEHrTbJDMkpNFtFw0XdQTT904vQNn8wml3Lck32w",
    "office_valid_expired": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6Ii1LSTNROW5OUjdiUm9meG1lWm9YcWJIWkdldyJ9.eyJhdWQiOiIzMTE3YmU1YS0zMzIzLTQ1M2YtODEwZC04Nzk1YmFjN2YzMWQiLCJpc3MiOiJodHRwczovL2xvZ2luLm1pY3Jvc29mdG9ubGluZS5jb20vN2JkMjJlODQtMzRiMS00YjdiLWI2ZjctNGNkN2RhMGE1ZTRhL3YyLjAiLCJpYXQiOjE2OTQ3ODQyMzcsIm5iZiI6MTY5NDc4NDIzNywiZXhwIjoxNjk0NzkyNzEyLCJhaW8iOiJBWFFBaS84VUFBQUFKNTlNcTk2UVBwYkZabUltNGtCRGRvRHZPaHJwREx3UDVzNlVNbklmcS9UNWR4R3BsZUIyTG9wVzZhVk5OYm4xbFlQTnFuOHRiMk5QS1A3NnNlRnc1ano3aktoMGppZDkzRXZFUFAzUzNhcTZ2c25JbFNJVmJGZzViUjNGZlgvKzNmdWNBZUJ3elo5aVRTckY1dk5YNkE9PSIsImF6cCI6ImQzNTkwZWQ2LTUyYjMtNDEwMi1hZWZmLWFhZDIyOTJhYjAxYyIsImF6cGFjciI6IjAiLCJuYW1lIjoiTHVrYXMgU21pdGgiLCJvaWQiOiJiMjNhOTc4My05NDdhLTRkMDgtYWMyYy02ZDE5ZjFlNTYwYWUiLCJwcmVmZXJyZWRfdXNlcm5hbWUiOiJsdWthcy5zbWl0aEB3aXR0eS53b3JrcyIsInJoIjoiMC5BWUVBaEM3U2U3RTBlMHUyOTB6WDJncGVTbHEtRnpFak16OUZnUTJIbGJySDh4MkJBSVUuIiwic2NwIjoiYWNjZXNzX2FzX3VzZXIiLCJzdWIiOiJtcnMzdGVZVVdXblFyX2syakxDd1pleXRpZUVlWHBZV0ZHaTBCRWx2blFJIiwidGlkIjoiN2JkMjJlODQtMzRiMS00YjdiLWI2ZjctNGNkN2RhMGE1ZTRhIiwidXRpIjoid0RXOUdRMTFaa0NsS2lFaTNBbVJBQSIsInZlciI6IjIuMCJ9.ZQ6LuAHdQALJO5Wq05eXlz19NUEUs9bOQ54l8DDwZ-_0hOKhc6-USvNMXYKl6TV_o20c2cC5UgR5zKMEbXoLPpdcgzngH-S46cQsCVZollIzeSV21NC-APEF2FreSw91xxeFI6Mq9sGYUsbCi9k08aPnEMM_dtciNbXtcTg7y7ChCOQE4NcKHfsU9XGlbHku1isBUmLNDG7dcDFISAU0Sufws1TKwN3NIAlZSr52HAiSPV926caGpIAtghAarGEkSOlS52qMlboNVw5zhCZKu-AgplQR5artgJDbCs-yVNwHgO2VVNUeQmL8H16IJlCeFxCtJvVOWM_DTBQTdzyZcQ",
    "other_valid_expired": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
}

logging.basicConfig(
    level="DEBUG", format="[%(asctime)s] %(name)s %(levelname)s - %(message)s"
)


def get_dirs(path):
    return list(
        subpath for subpath in Path(path).iterdir() if not subpath.name.startswith(".")
    )


def test_read_main():
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 200


def test_health():
    with TestClient(app) as client:
        response = client.get("/health", follow_redirects=False)
        assert response.status_code == 200


@pytest.mark.parametrize(
    "highlight_position_dir",
    get_dirs("tests/test_highlight_position"),
)
def test_highlight_position(highlight_position_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = highlight_position_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = highlight_position_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "sentry_examples_dir",
    get_dirs("tests/test_sentry_examples"),
)
def test_sentry_examples(sentry_examples_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = sentry_examples_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = sentry_examples_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "spacy_model_dir",
    get_dirs("tests/test_spacy_model"),
)
def test_spacy_model(spacy_model_dir, snapshot):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = spacy_model_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = spacy_model_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "chunking_issues_dir",
    get_dirs("tests/test_chunking_issues"),
)
def test_chunking_issues_dir(chunking_issues_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = chunking_issues_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = chunking_issues_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "demo_wordings_english_dir",
    get_dirs("tests/test_demo_wordings_english"),
)
def test_demo_wordings_english(demo_wordings_english_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = demo_wordings_english_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = demo_wordings_english_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "demo_wordings_german_dir",
    get_dirs("tests/test_demo_wordings_german"),
)
def test_demo_wordings_german(demo_wordings_german_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = demo_wordings_german_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = demo_wordings_german_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "general_case_dir",
    get_dirs("tests/test_general_cases"),
)
def test_general_cases(general_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = general_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = general_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_witty_free_dir",
    get_dirs("tests/test_witty_free"),
)
def test_witty_free_json(test_witty_free_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = test_witty_free_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "free@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_witty_free_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "orthoraphy_case_dir",
    get_dirs("tests/test_languagetool"),
)
def test_orthoraphy(orthoraphy_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = orthoraphy_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = orthoraphy_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_gender_ending"),
)
def test_gender_ending(ending_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = ending_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = ending_case_dir
        snapshot.assert_match(output, "output.json")


def test_api_missing_data():
    with TestClient(app) as client:
        response = client.post("/v2.3/check")
        assert response.status_code == 422


@pytest.mark.parametrize(
    "detection_case_dir",
    get_dirs("tests/test_language_detection"),
)
def test_language_detection(detection_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = detection_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = detection_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "fails_case_dir",
    get_dirs("tests/test_fails"),
)
def test_language_detection_fail(fails_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = fails_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 422

        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = fails_case_dir
        snapshot.assert_match(output, "output.json")


def test_lemmatize():
    with TestClient(app) as client:
        response = client.get("/lemmatize?lang=en&text=running")
        assert response.status_code == 200
        result = response.json()

        assert result == "run"


def test_tokenize():
    with TestClient(app) as client:
        response = client.get("/tokenize?lang=en&text=running23 is the best.")
        assert response.status_code == 200
        result = response.json()

        assert result == ["running23", "is", "the", "best", "."]


def test_validate_word_type():
    with TestClient(app) as client:
        url = "/validate-word-type?lang=en&text=running is the best&"
        response = client.get(url)
        assert response.status_code == 422

        response = client.get(url + "word_types=s")
        assert response.status_code == 422

        response = client.get(url + "word_types=s|~v|s|c")
        assert response.status_code == 422

        response = client.get(url + "word_types=s|~v|s|conj")
        result = response.json()

        assert result == "ok"


def test_invalid_access_token():
    with TestClient(app) as client:
        input_json = '{"text": "Hello world."}'

        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"authorization": "bearer invalid"},
        )

        assert response.status_code == 403


def test_config_changed(set_redis):
    with TestClient(app) as client:
        input_json = '{"text": "Hello world.", "config_hash": "foo"}'

        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )

        assert response.status_code == 200
        response_content = json.loads(response.content)
        assert "config_changed" not in response_content


def test_config_changed(set_redis):
    with TestClient(app) as client:
        input_json = '{"text": "Hello world.", "config_hash": "foo"}'

        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "test@gmail.com"},
        )

        assert response.status_code == 200
        response_content = json.loads(response.content)
        assert response_content["config_changed"] is True


def test_config_organization_changed(set_redis):
    with TestClient(app) as client:
        input_json = '{"text": "Hello world.", "organization_config_hash": "bar"}'

        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "test@gmail.com"},
        )

        assert response.status_code == 200
        response_content = json.loads(response.content)
        assert response_content["config_changed"] is True


@pytest.fixture
def set_redis():
    # 2_2@gmail.com
    user_object = {
        "id": "test-2_2",
        "email": "2_2@gmail.com",
        "organization_id": "test-2_2-org",
        "name": "Tests 2_2",
        "config": {},
        "false_positives": [],
        "term_replacements": {},
        "notifications": 0,
    }

    redis.set(user_object["email"], json.dumps(user_object))

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Team 2_2",
        "plan": "witty_free",
        "config": {},
        "false_positives": [],
        "term_replacements": {},
    }

    redis.set(organization_object["id"], json.dumps(organization_object))
    # free@gmail.com
    user_object = {
        "id": "test-free",
        "email": "free@gmail.com",
        "organization_id": "test-free-org",
        "name": "Tests Free",
        "config": {"categories": {}},
        "false_positives": [],
        "term_replacements": {},
        "notifications": 0,
    }

    redis.set(user_object["email"], json.dumps(user_object))

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Free",
        "plan": "witty_free",
        "config": {"categories": {}},
        "false_positives": [],
        "term_replacements": {},
    }

    redis.set(organization_object["id"], json.dumps(organization_object))

    # default@gmail.com
    user_object = {
        "id": "test-default",
        "email": "default@gmail.com",
        "organization_id": "test-default-org",
        "name": "Tests Default",
        "config": {
            "categories": {
                "advanced_plain_language": {"value": False, "status": "force"},
            },
        },
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "notifications": 0,
        "config_hash": None,
        "team_analytics": False,
    }

    redis.set(user_object["email"], json.dumps(user_object))

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Default",
        "plan": "witty_teams",
        "config": {"categories": {}},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
    }

    redis.set(organization_object["id"], json.dumps(organization_object))

    # test@gmail.com
    user_object = {
        "id": "test-user",
        "email": "test@gmail.com",
        "organization_id": "test-org",
        "name": "Tests User",
        "config": {
            "preferred_variants": {
                "value": ["en-GB"],
                "status": "force",
            },
            "german_gender_ending": {
                "value": "In",
                "status": "force",
            },
            "categories": {
                "advanced_plain_language": {"value": False, "status": "force"},
                "emotional_security": {"value": True, "status": "force"},
                "abbreviation": {"value": False, "status": "force"},
                "belief": {"value": True, "status": "force"},
            },
        },
        "false_positives": [
            "Führungskraft",
            "Führungskräfte",
            "Führungskräften",
        ],
        "term_replacements": {
            "foo bar|en": {
                "alternatives": ["ding ding"],
                "word_type": "=",
                "explanation": {
                    "text": "better ding",
                    "icon": None,
                    "url": "https://witty.works/foo bar",
                },
                "proficiency_level": "unconscious_bias",
            },
            "foo bar|de": {
                "alternatives": ["ding ding"],
                "word_type": "=",
                "explanation": {
                    "text": "better ding",
                    "icon": None,
                    "url": None,
                },
                "proficiency_level": "unconscious_bias",
            },
            "welt|de": {
                "alternatives": ["world"],
                "lang": "de",
                "explanation": {
                    "text": "better world",
                    "icon": "🥰",
                    "url": "https://witty.works/welt",
                },
                "proficiency_level": "unconscious_bias",
            },
            "run": {
                "lang": "en",
                "word_type": "v",
                "alternatives": ["walk"],
                "explanation": {
                    "text": "better not run",
                    "icon": "💡",
                    "url": "https://witty.works/run",
                },
                "proficiency_level": "unconscious_bias",
            },
        },
        "domains": {
            "type": "deny",
            "list": ["foo.com", "bar.de"],
        },
        "config_hash": "foobar",
        "notifications": 5,
        "has_consented_to_mailing": True,
        "team_analytics": True,
    }

    redis.set(user_object["email"], json.dumps(user_object))

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Witty Works",
        "plan": "witty_teams",
        "config": {
            "store_context": {
                "value": True,
                "status": "force",
            },
            "preferred_variants": {
                "value": ["en-GB"],
                "status": "force",
            },
            "german_gender_ending": {
                "value": "*in",
                "status": "suggestion",
            },
            "gendered_roles_format": {
                "value": "binary_gender",
                "status": "force",
            },
            "categories": {
                "emotional_security": {"value": False, "status": "force"},
                "abbreviation": {"value": True, "status": "force"},
                "orthography": {"value": True, "status": "force"},
                "belief": {"value": False, "status": "force"},
            },
        },
        "false_positives": [
            "stark",
            "starke",
            "starkes",
            "starker",
        ],
        "term_replacements": {
            "dong|en": {
                "alternatives": ["ding"],
                "explanation": {
                    "text": "better dong",
                    "icon": "🥰",
                    "url": "https://witty.works",
                },
            },
            "dong|de": {
                "alternatives": ["ding"],
                "explanation": {
                    "text": "better dong",
                    "icon": "🥰",
                    "url": "https://witty.works",
                },
            },
            "welt|de": {
                "alternatives": ["globus (welt)"],
                "lang": "de",
                "explanation": {
                    "text": "better globus",
                    "icon": "🥰",
                    "url": "https://witty.works/welt",
                },
            },
        },
        "domains": {
            "type": "allow",
            "list": ["hello.com"],
        },
        "config_hash": "foobaz",
    }

    # Set a value
    redis.set(organization_object["id"], json.dumps(organization_object))


@pytest.mark.parametrize(
    "test_false_positive_dir",
    get_dirs("tests/test_false_positive"),
)
def test_false_positive(test_false_positive_dir, snapshot, set_redis):
    with TestClient(app) as client:
        input_json = test_false_positive_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "test@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_false_positive_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_not_logged_in_dir",
    get_dirs("tests/test_not_logged_in"),
)
def test_not_logged_in(test_not_logged_in_dir, snapshot):
    with TestClient(app) as client:
        input_json = test_not_logged_in_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post("/v2.3/check", json=json.loads(input_json))
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_not_logged_in_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_term_replacement_dir",
    get_dirs("tests/test_term_replacement"),
)
def test_term_replacement(test_term_replacement_dir, snapshot, set_redis):
    with TestClient(app) as client:
        input_json = test_term_replacement_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "test@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_term_replacement_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_auth_2_0_dir",
    get_dirs("tests/test_auth_2_0"),
)
def test_auth_2_0(test_auth_2_0_dir, snapshot, set_redis):
    with TestClient(app) as client:
        response = client.post("/v2.0/auth")
        assert response.status_code == 403

        response = client.post("/v2.0/auth", headers={"X-Auth": "missing@gmail.com"})
        assert response.status_code == 403

        response = client.post("/v2.0/auth", headers={"X-Auth": "test@gmail.com"})
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_auth_2_0_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_auth_2_0_team_analytics_opt_out_dir",
    get_dirs("tests/test_auth_2_0_team_analytics_opt_out"),
)
def test_auth_2_0_team_analytics_opt_out(
    test_auth_2_0_team_analytics_opt_out_dir, snapshot, set_redis
):
    with TestClient(app) as client:
        response = client.post("/v2.0/auth", headers={"X-Auth": "default@gmail.com"})
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_auth_2_0_team_analytics_opt_out_dir
        snapshot.assert_match(output, "output.json")


def test_auth_token_validation():
    with TestClient(app) as client:
        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"Authorization": "Bearer " + tokens["azureadbc_valid_expired"]},
        )
        assert response.status_code == 403

        response = client.post(
            "/v2.3/check",
            json={"text": "Hallo Kunde"},
            headers={"Authorization": "Bearer " + tokens["office_valid_expired"]},
        )
        assert response.status_code == 403


@pytest.mark.parametrize(
    "test_disable_categories_dir",
    get_dirs("tests/test_disable_categories"),
)
def test_disable_categories(test_disable_categories_dir, snapshot, set_redis):
    with TestClient(app) as client:
        input_json = test_disable_categories_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "test@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_disable_categories_dir
        snapshot.assert_match(output, "output.json")


def test_validate_scope(event_loop, set_redis):
    try:
        claims = __validate_scope("access_as_user", tokens["azureadbc_valid_expired"])
    except:
        claims = False

    assert claims is not False

    try:
        claims = __validate_scope("access_as_user", tokens["other_valid_expired"])
    except:
        claims = False

    assert claims is False


def test_token(event_loop, set_redis):
    try:
        token = __get_token("")
    except AuthError as e:
        token = False

    assert token is False

    try:
        token = __get_token("invalid")
    except AuthError as e:
        token = False

    assert token is False

    token = __get_token("bearer invalid")
    assert token == "invalid"

    token = __get_token("bearer " + tokens["azureadbc_valid_expired"])
    assert token == tokens["azureadbc_valid_expired"]


def test_token_claims(event_loop, set_redis):
    claims = __get_token_claims(tokens["azureadbc_valid_expired"])

    assert claims is not False


# test overwriting user configuration by organization forced rules
def test_fetch_configs_for_request(event_loop, set_redis):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {
            "store_context": False,
            "primary_language": "de-DE",
            "preferred_languages": "de",
            "preferred_variants": "de-DE",
            "german_gender_ending": "/in",
            "gendered_roles_format": "inclusive_gender",
        },
    }
    test_request = RequestIn(**request_data)
    event_loop.run_until_complete(
        fetch_configs_for_request(2.3, test_request, "test@gmail.com")
    )
    assert hasattr(test_request.config, "store_context")
    assert test_request.config.store_context is True
    assert test_request.config.preferred_variants == ["en-GB"]
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test not overwriting user configuration by organization suggestion/default rules


def test_fetch_user_rules_suggestion(event_loop, set_redis):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {
            "primary_language": "de-DE",
            "preferred_languages": "de",
            "preferred_variants": "de-DE",
            "german_gender_ending": "/in",
            "gendered_roles_format": "inclusive_gender",
        },
    }
    test_request = RequestIn(**request_data)
    event_loop.run_until_complete(
        fetch_configs_for_request(2.3, test_request, "non_existant@gmail.com")
    )
    assert test_request.config.store_context is True
    assert test_request.config.primary_language == "de-DE"
    assert test_request.config.preferred_languages == ["de"]
    assert test_request.config.preferred_variants == ["de-DE"]
    assert test_request.config.german_gender_ending == "/in"
    assert test_request.config.gendered_roles_format == "inclusive_gender"


# test user not set any parameters, but organization did


def test_set_organization_rules(event_loop, set_redis):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = RequestIn(**request_data)
    event_loop.run_until_complete(
        fetch_configs_for_request(2.3, test_request, "test@gmail.com")
    )
    assert test_request.config.store_context is True
    assert test_request.config.preferred_variants == ["en-GB"]
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test user and organization didn't set any rules


def test_set_default_rules(event_loop):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = RequestIn(**request_data)

    event_loop.run_until_complete(
        fetch_configs_for_request(2.3, test_request, "non_existant@gmail.com")
    )
    assert test_request.config.store_context is True
    assert test_request.config.primary_language is None
    assert test_request.config.preferred_languages == [
        LangWithAutoType.EN,
        LangWithAutoType.DE,
    ]
    assert test_request.config.preferred_variants == [
        LangWithAutoType.enUS,
        LangWithAutoType.deDE,
    ]
    assert test_request.config.german_gender_ending == "*in"
    assert test_request.config.gendered_roles_format == "both"


def assert_rules(response, request_data, key_prefix=""):
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert (
        response_content[key_prefix + "config"]["gendered_roles_format"]
        == request_data["config"]["gendered_roles_format"]
    )
    assert (
        response_content[key_prefix + "config"]["german_gender_ending"]
        == request_data["config"]["german_gender_ending"]
    )
    assert (
        response_content[key_prefix + "false_positives"]
        == request_data["false_positives"]
    )
    assert (
        response_content[key_prefix + "term_replacements"]
        == request_data["term_replacements"]
    )


# test POST Redis endpoint
def test_store_get_delete_rules():
    user_request_data = {
        "id": "foo:123",
        "email": "foo@bar.com",
        "name": "Test User",
        "config_hash": "foobar",
        "organization_id": "TEST_organization",
        "config": {
            "preferred_variants": {
                "value": ["en-GB"],
                "status": "force",
            },
            "store_context": {
                "value": True,
                "status": "force",
            },
            "gendered_roles_format": {
                "value": "binary_gender",
                "status": "force",
            },
            "german_gender_ending": {
                "value": "In",
                "status": "suggestion",
            },
            "categories": {
                "emotional_security": {"value": True, "status": "force"},
            },
        },
        "false_positives": ["ding", "dong"],
        "term_replacements": {
            "hello|en": {
                "alternatives": ["world"],
                "explanation": {
                    "text": "better hello",
                    "icon": "🥰",
                    "url": "https://witty.works",
                },
                "proficiency_level": "unconscious_bias",
            },
            "hello|de": {
                "alternatives": ["world"],
                "explanation": {
                    "text": "better hello",
                    "icon": "🥰",
                    "url": "https://witty.works",
                },
                "proficiency_level": "unconscious_bias",
            },
            "bim|en": {
                "alternatives": ["bam"],
                "explanation": {
                    "text": "better bim",
                    "icon": "🥰",
                    "url": "https://witty.works",
                },
            },
            "bim|de": {
                "alternatives": ["bam"],
                "explanation": {
                    "text": "better bim",
                    "icon": "🥰",
                    "url": "https://witty.works",
                },
            },
        },
        "domains": {
            "type": "deny",
            "list": ["foo.bar"],
        },
    }

    with TestClient(app) as client:
        # check user is missing
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 404

        # create user rules
        response = client.post("/user/configs", json=user_request_data)
        assert_rules(response, user_request_data)

        # update user rules
        user_request_data["config"]["gendered_roles_format"]["value"] = "none"
        response = client.post("/user/configs", json=user_request_data)
        assert_rules(response, user_request_data)

        # check user is missing
        response = client.get("/user/configs?email=bar")
        assert response.status_code == 404

        # check user exists
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert_rules(response, user_request_data)

        # check user is missing can be deleted
        response = client.delete("/user/configs?email=foobar")
        assert response.status_code == 204

        # check user is deleted
        response = client.delete("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 204

        organization_request_data = {
            "id": "TEST_organization",
            "name": "Witty Works",
            "plan": "witty_teams",
            "config_hash": "foobaz",
            "config": {
                "preferred_variants": {
                    "value": ["en-GB"],
                    "status": "force",
                },
                "store_context": {
                    "value": True,
                    "status": "force",
                },
                "gendered_roles_format": {
                    "value": "binary_gender",
                    "status": "force",
                },
                "german_gender_ending": {
                    "value": "In",
                    "status": "suggestion",
                },
                "categories": {
                    "emotional_security": {"value": True, "status": "force"},
                },
            },
            "false_positives": ["hello", "world", "dong"],
            "term_replacements": {
                "hello|en": {
                    "alternatives": ["world"],
                    "explanation": {
                        "text": "better world",
                        "icon": "🥰",
                        "url": "https://witty.works/hello",
                    },
                    "proficiency_level": "unconscious_bias",
                },
                "hello|de": {
                    "alternatives": ["world"],
                    "explanation": {
                        "text": "better world",
                        "icon": "🥰",
                        "url": "https://witty.works/hello",
                    },
                    "proficiency_level": "unconscious_bias",
                },
                "foo|en": {
                    "alternatives": ["bar"],
                    "word_type": "=",
                    "explanation": {
                        "text": "better bar",
                        "icon": "🥰",
                        "url": "https://witty.works/foo",
                    },
                },
                "foo|de": {
                    "alternatives": ["bar"],
                    "word_type": "=",
                    "explanation": {
                        "text": "better bar",
                        "icon": "🥰",
                        "url": "https://witty.works/foo",
                    },
                },
            },
            "domains": {
                "type": "allow",
                "list": [
                    "foo.bar",
                    "hello.de",
                ],
            },
        }

        # check organization is missing
        response = client.get(
            "/organization/configs?organization_id=" + organization_request_data["id"]
        )
        assert response.status_code == 404

        # check organization is created
        response = client.post("/organization/configs", json=organization_request_data)
        assert_rules(response, organization_request_data)

        # check organization is updated
        organization_request_data["config"]["gendered_roles_format"]["value"] = "both"
        response = client.post("/organization/configs", json=organization_request_data)
        assert_rules(response, organization_request_data)

        # check user is missing
        response = client.get("/user/configs?email=bar")
        assert response.status_code == 404

        # check user is still missing
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 404

        # check user is created
        response = client.post("/user/configs", json=user_request_data)
        assert response.status_code == 200

        # check user exists
        response = client.get("/user/configs?email=" + user_request_data["email"])

        assert_rules(response, user_request_data)
        assert_rules(response, organization_request_data, "organization_")

        # check organization missing can be deleted
        response = client.delete("/organization/configs?organization_id=foobar")
        assert response.status_code == 204

        # check organization deleted
        response = client.delete(
            "/organization/configs?organization_id=TEST_organization"
        )
        assert response.status_code == 204

        # check deleted organization reverts to user rules
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert_rules(response, user_request_data)


def test_german_gender_ending():
    with TestClient(app) as client:
        request_data = {
            "alternative": "Sinti~ze~/~Sinti und Rom~nja~/~Roma",
        }
        response = client.get("/debug/german_gender_ending", params=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = [
            "Sinti*ze und Rom*nja",
            "Sintize/Sinti und Romnja/Roma",
            "Sinti_ze und Rom_nja",
            "SintiZe und RomNja",
            "Sinti/ze und Rom/nja",
            "Sinti:ze und Rom:nja",
            "Sinti/-ze und Rom/-nja",
        ]

        assert sorted(response_content) == sorted(expected)


def test_rule():
    with TestClient(app) as client:
        request_data = {
            "text": "She has special needs",
            "lang": "en",
            "lemma": "have special need",
            "function": "simple_match",
            "word_types": "v|a|s",
            "lower_case": True,
            "alternatives": "foo|   bar | ding --- dong",
            "plural_alternatives": None,
        }
        response = client.get("/debug/rule", params=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = {
            "results": [
                {
                    "text": "has special needs",
                    "context": "She has special needs",
                    "category": "corporate_rules",
                    "subcategory": "corporate_rules",
                    "start": 4,
                    "end": 21,
                    "alternatives": [
                        {"text": "foo"},
                        {"text": "bar"},
                        {"text": "ding", "context": "dong"},
                    ],
                    "label": "Dictionary",
                    "explanation": {"text": "", "icon": "❗"},
                    "gravity": 0.9,
                }
            ],
            "language": "en",
            "limit_reached": False,
        }

        assert response_content == expected


def test_spacy():
    with TestClient(app) as client:
        request_data = {
            "text": "👩🏻‍🚒 Das ist sehr ehrgeizig Herr Müller in London 😃",
            "lang": "de",
        }
        response = client.get("/debug/spacy", params=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = [
            {"word_type": "emoji|~s|~|a|a|s||||emoji"},
            {
                "text": "👩🏻‍🚒",
                "lemma": "👩🏻‍🚒",
                "ner": "",
                "start": 0,
                "tag": "NE",
                "pos": "PROPN",
                "dep": "ROOT",
                "word_types": ["emoji"],
                "morph": {"Case": "Nom", "Gender": "Fem", "Number": "Sing"},
                "is_emoji": True,
                "is_singular": True,
                "emoji_desc": "woman firefighter light skin tone",
                "whitespace": " ",
            },
            {
                "text": "Das",
                "lemma": "der",
                "ner": "",
                "start": 5,
                "tag": "PDS",
                "pos": "PRON",
                "dep": "sb",
                "word_types": ["s"],
                "morph": {
                    "Case": "Nom",
                    "Gender": "Neut",
                    "Number": "Sing",
                    "PronType": "Dem",
                },
                "is_emoji": False,
                "is_singular": True,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "ist",
                "lemma": "sein",
                "ner": "",
                "start": 9,
                "tag": "VAFIN",
                "pos": "AUX",
                "dep": "ROOT",
                "word_types": [],
                "morph": {
                    "Mood": "Ind",
                    "Number": "Sing",
                    "Person": "3",
                    "Tense": "Pres",
                    "VerbForm": "Fin",
                },
                "is_emoji": False,
                "is_singular": True,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "sehr",
                "lemma": "sehr",
                "ner": "",
                "start": 13,
                "tag": "ADV",
                "pos": "ADV",
                "dep": "mo",
                "word_types": ["a"],
                "morph": {},
                "is_emoji": False,
                "is_singular": None,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "ehrgeizig",
                "lemma": "ehrgeizig",
                "ner": "",
                "start": 18,
                "tag": "ADJD",
                "pos": "ADV",
                "dep": "mo",
                "word_types": ["a"],
                "morph": {"Degree": "Pos"},
                "is_emoji": False,
                "is_singular": None,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "Herr",
                "lemma": "Herr",
                "ner": "",
                "start": 28,
                "tag": "NN",
                "pos": "NOUN",
                "dep": "pd",
                "word_types": ["s"],
                "morph": {"Case": "Nom", "Gender": "Masc", "Number": "Sing"},
                "is_emoji": False,
                "is_singular": True,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "Müller",
                "lemma": "Müller",
                "ner": "",
                "start": 33,
                "tag": "NE",
                "pos": "PROPN",
                "dep": "nk",
                "word_types": [],
                "morph": {"Case": "Nom", "Gender": "Masc", "Number": "Sing"},
                "is_emoji": False,
                "is_singular": True,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "in",
                "lemma": "in",
                "ner": "",
                "start": 40,
                "tag": "APPR",
                "pos": "ADP",
                "dep": "mo",
                "word_types": [],
                "morph": {},
                "is_emoji": False,
                "is_singular": None,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "London",
                "lemma": "London",
                "ner": "LOC",
                "start": 43,
                "tag": "NE",
                "pos": "PROPN",
                "dep": "nk",
                "word_types": [],
                "morph": {"Case": "Dat", "Gender": "Neut", "Number": "Sing"},
                "is_emoji": False,
                "is_singular": True,
                "emoji_desc": None,
                "whitespace": " ",
            },
            {
                "text": "😃",
                "lemma": "😃",
                "ner": "",
                "start": 50,
                "tag": "KON",
                "pos": "CCONJ",
                "dep": "punct",
                "word_types": ["emoji"],
                "morph": {},
                "is_emoji": True,
                "is_singular": None,
                "emoji_desc": "grinning face with big eyes",
                "whitespace": "",
            },
        ]

        assert response_content == expected


@pytest.mark.parametrize(
    "lemma_case_dir",
    get_dirs("tests/test_lemmatizers"),
)
def test_lemmatizer(lemma_case_dir, snapshot):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = lemma_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = lemma_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "grammatical_alternatives_case_dir",
    get_dirs("tests/test_grammatically_correct_alternatives"),
)
def test_grammatically_correct_alternatives(
    grammatical_alternatives_case_dir, snapshot, set_redis
):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = grammatical_alternatives_case_dir.joinpath(
            "input.json"
        ).read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = grammatical_alternatives_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "abbr_case_dir",
    get_dirs("tests/test_abbreviation"),
)
def test_abbreviation(abbr_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = abbr_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = abbr_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_sing_or_plur_dir",
    get_dirs("tests/test_sing_or_plur"),
)
def test_sing_or_plur(test_sing_or_plur_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = test_sing_or_plur_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_sing_or_plur_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "uberlegen_word_type_dir",
    get_dirs("tests/test_uberlegen_word_type"),
)
def test_uberlegen_word_type(uberlegen_word_type_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = uberlegen_word_type_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = uberlegen_word_type_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "english_false_pos_pattern_case_dir",
    get_dirs("tests/test_english_false_positives_pattern"),
)
def test_english_false_positive_pattern(
    english_false_pos_pattern_case_dir, snapshot, set_redis
):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = english_false_pos_pattern_case_dir.joinpath(
            "input.json"
        ).read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = english_false_pos_pattern_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "english_upper_case_multiterms_dir",
    get_dirs("tests/test_english_upper_case_multiterms"),
)
def test_english_upper_case_multiterms(
    english_upper_case_multiterms_dir, snapshot, set_redis
):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = english_upper_case_multiterms_dir.joinpath(
            "input.json"
        ).read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = english_upper_case_multiterms_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "german_plain_language_dir",
    get_dirs("tests/test_german_plain_language"),
)
def test_german_plain_language(german_plain_language_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = german_plain_language_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.3/check",
            json=json.loads(input_json),
            headers={"X-Auth": "free@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = german_plain_language_dir
        snapshot.assert_match(output, "output.json")
