import base64
import pytest
import logging
import json
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from app.main import (
    app,
    context,
)
from app.categories import get_category_keys
from app.prompt import Prompt
from app.config_manager import (
    debug_configs,
    fetch_configs_for_request,
    parse_term_replacements,
)
from app.auth_service import (
    AuthError,
    convert_to_pem,
    validate_scope_,
    get_token_,
    get_unverified_token_claims_,
)
from app.models import (
    Config,
    LangVariantType,
    LangWithAutoType,
    CheckRequestIn,
    LlmAccessType,
)

tokens = {
    "azureadbc_valid_expired": "eyJhbGciOiJSUzI1NiIsImtpZCI6IkN6d1lJSEUyNG5oRFNTdkhhT1pxaVNwTFV4UkFXZjluQ2kydEtnMXRCME0iLCJ0eXAiOiJKV1QifQ.eyJjdXJyZW50VGltZSI6MTY5NDU4OTkxMSwiZW1haWwiOiJsdWthcy5zbWl0aEB3aXR0eS53b3JrcyIsIm5hbWUiOiJmb28iLCJpZHAiOiJnb29nbGUuY29tIiwic3ViIjoiMjVlMDUwYTUtYTJmZC00MzZmLWE1YmUtM2I5NmZmZDAxOTU4Iiwib3RoZXJNYWlscyI6WyJsdWthcy5zbWl0aEB3aXR0eS53b3JrcyJdLCJleHRlbnNpb25fdGVybXNPZlVzZUNvbnNlbnREYXRlVGltZSI6MTY2Mjg5Mjk2OCwiZXh0ZW5zaW9uX01haWxpbmdDb25zZW50ZWQiOiJZZXMiLCJ0ZXJtc09mVXNlQ29uc2VudFJlcXVpcmVkIjpmYWxzZSwidGlkIjoiODE5MzJmZTEtZjI1ZS00M2ZjLWI2NzQtMDAyZmY4MjM1Mzg5Iiwic2NwIjoiYWNjZXNzX2FzX3VzZXIiLCJhenAiOiI3ZTA5MDMwOC01NzVhLTRlN2QtODRlNC03OGM4M2QwODNhYjYiLCJ2ZXIiOiIxLjAiLCJpYXQiOjE2OTQ1ODk5NjIsImF1ZCI6IjdlMDkwMzA4LTU3NWEtNGU3ZC04NGU0LTc4YzgzZDA4M2FiNiIsImV4cCI6MTY5NDY3NjM2MiwiaXNzIjoiaHR0cHM6Ly93aXR0eXdvcmtzZGV2LmIyY2xvZ2luLmNvbS84MTkzMmZlMS1mMjVlLTQzZmMtYjY3NC0wMDJmZjgyMzUzODkvdjIuMC8iLCJuYmYiOjE2OTQ1ODk5NjJ9.JtXTKr8pUEBQ5-hO1ak-L1IocXQdOW6rNaCS5DD1DAvt8ldo-n9APQVw8mqWlYmukrelqH48VwguYiCcD5-Lc8seWfX5lywXT4mnfsJscqGQr7iVL1s6GNBp2wsaRLNf6l8qzIVWa0UDREACdgUpJRmbvObILZa6z42E5ghOO9RxxVCsCKg6hwKKhtY2w6UEs1u26JF7BKHH7XFoX88CfG-kqVfhVw_zb_bOIhDrEGflWZzKdKx9LfaLS1VQjVY1I_IW1nL1EQaBo286MHpzLdxzeyLf6Jo9ASzgAeEqKD6v2PPEHrTbJDMkpNFtFw0XdQTT904vQNn8wml3Lck32w",
    "office_valid_expired": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6Ii1LSTNROW5OUjdiUm9meG1lWm9YcWJIWkdldyJ9.eyJhdWQiOiIzMTE3YmU1YS0zMzIzLTQ1M2YtODEwZC04Nzk1YmFjN2YzMWQiLCJpc3MiOiJodHRwczovL2xvZ2luLm1pY3Jvc29mdG9ubGluZS5jb20vN2JkMjJlODQtMzRiMS00YjdiLWI2ZjctNGNkN2RhMGE1ZTRhL3YyLjAiLCJpYXQiOjE2OTQ3ODQyMzcsIm5iZiI6MTY5NDc4NDIzNywiZXhwIjoxNjk0NzkyNzEyLCJhaW8iOiJBWFFBaS84VUFBQUFKNTlNcTk2UVBwYkZabUltNGtCRGRvRHZPaHJwREx3UDVzNlVNbklmcS9UNWR4R3BsZUIyTG9wVzZhVk5OYm4xbFlQTnFuOHRiMk5QS1A3NnNlRnc1ano3aktoMGppZDkzRXZFUFAzUzNhcTZ2c25JbFNJVmJGZzViUjNGZlgvKzNmdWNBZUJ3elo5aVRTckY1dk5YNkE9PSIsImF6cCI6ImQzNTkwZWQ2LTUyYjMtNDEwMi1hZWZmLWFhZDIyOTJhYjAxYyIsImF6cGFjciI6IjAiLCJuYW1lIjoiTHVrYXMgU21pdGgiLCJvaWQiOiJiMjNhOTc4My05NDdhLTRkMDgtYWMyYy02ZDE5ZjFlNTYwYWUiLCJwcmVmZXJyZWRfdXNlcm5hbWUiOiJsdWthcy5zbWl0aEB3aXR0eS53b3JrcyIsInJoIjoiMC5BWUVBaEM3U2U3RTBlMHUyOTB6WDJncGVTbHEtRnpFak16OUZnUTJIbGJySDh4MkJBSVUuIiwic2NwIjoiYWNjZXNzX2FzX3VzZXIiLCJzdWIiOiJtcnMzdGVZVVdXblFyX2syakxDd1pleXRpZUVlWHBZV0ZHaTBCRWx2blFJIiwidGlkIjoiN2JkMjJlODQtMzRiMS00YjdiLWI2ZjctNGNkN2RhMGE1ZTRhIiwidXRpIjoid0RXOUdRMTFaa0NsS2lFaTNBbVJBQSIsInZlciI6IjIuMCJ9.ZQ6LuAHdQALJO5Wq05eXlz19NUEUs9bOQ54l8DDwZ-_0hOKhc6-USvNMXYKl6TV_o20c2cC5UgR5zKMEbXoLPpdcgzngH-S46cQsCVZollIzeSV21NC-APEF2FreSw91xxeFI6Mq9sGYUsbCi9k08aPnEMM_dtciNbXtcTg7y7ChCOQE4NcKHfsU9XGlbHku1isBUmLNDG7dcDFISAU0Sufws1TKwN3NIAlZSr52HAiSPV926caGpIAtghAarGEkSOlS52qMlboNVw5zhCZKu-AgplQR5artgJDbCs-yVNwHgO2VVNUeQmL8H16IJlCeFxCtJvVOWM_DTBQTdzyZcQ",
    "other_valid_expired": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
    "third_party_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
}

logging.basicConfig(
    level="DEBUG", format="[%(asctime)s] %(name)s %(levelname)s - %(message)s"
)


def get_dirs(path):
    # id= keeps the test IDs stable when cases are added or removed;
    # without it pytest numbers the directories by position.
    return list(
        pytest.param(subpath, id=subpath.name)
        for subpath in sorted(Path(path).iterdir())
        if subpath.is_dir()
        and not subpath.name.startswith(".")
        and subpath.name != "__pycache__"
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
    "review_prompt_dir",
    get_dirs("tests/test_review_prompt"),
)
def test_review_prompt_dir(review_prompt_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = review_prompt_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/debug/review_prompt",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = review_prompt_dir
        snapshot.assert_match(output, "output.json")


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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
def test_spacy_model(spacy_model_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = spacy_model_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "free@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
        response = client.post("/v2.4/check")
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
def test_fails(fails_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = fails_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
        assert response.status_code == 422

        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = fails_case_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "rephrase_dir",
    get_dirs("tests/test_rephrase"),
)
def test_rephrase(rephrase_dir, snapshot, set_redis):
    if len(context.settings.aws_key):
        with TestClient(app) as client:
            # Read input files from the case directory.
            input_json = rephrase_dir.joinpath("input.json").read_text()
            # Call the tested endpoint.
            response = client.post(
                "/v1.0/rephrase",
                json=json.loads(input_json),
                headers={"X-TESTING-AUTH": "test@gmail.com"},
            )
            assert response.status_code == 200

            # output must be string
            output = json.dumps(
                response.json(), sort_keys=True, indent=4, ensure_ascii=False
            )
            # Snapshot the return value.
            snapshot.snapshot_dir = rephrase_dir
            snapshot.assert_match(output, "output.json")


def test_lemmatize():
    with TestClient(app) as client:
        response = client.get("/lemmatize?lang=en&text=running")
        assert response.status_code == 200
        result = response.json()

        assert result == "run"

        response = client.get("/lemmatize?lang=en&text=I am running up the hills.")
        assert response.status_code == 200
        result = response.json()

        assert result == None

        response = client.get(
            "/lemmatize?lang=en&text=I am running up the hills.&all=true"
        )
        assert response.status_code == 200
        result = response.json()

        assert result == ["I", "be", "run", "up", "the", "hill", "."]


def test_tokenize():
    with TestClient(app) as client:
        response = client.get("/tokenize?lang=en&text=running23 is the best.")
        assert response.status_code == 200
        result = response.json()

        assert result == ["running23", "is", "the", "best", "."]


def test_parse_word_types():
    with TestClient(app) as client:
        url = "/parse-word-types?lang=en&text=over-the-hill&"

        response = client.get(url + "word_types=")
        result = response.json()

        assert result == [
            {"word_type": "", "lower_case": True, "lemmatize": True},
        ]

        url = "/parse-word-types?lang=en&text=running is the best&"
        response = client.get(url)
        assert response.status_code == 422

        response = client.get(url + "word_types=")
        assert response.status_code == 422

        response = client.get(url + "word_types=n")
        assert response.status_code == 422

        response = client.get(url + "word_types=n|~v|n|c")
        assert response.status_code == 422

        response = client.get(url + "word_types=n|~v|n|=conj")
        result = response.json()

        assert result == [
            {"word_type": "n", "lower_case": True, "lemmatize": True},
            {"word_type": "v", "lower_case": True, "lemmatize": False},
            {"word_type": "n", "lower_case": True, "lemmatize": True},
            {"word_type": "conj", "lower_case": False, "lemmatize": False},
        ]


def test_invalid_access_token():
    with TestClient(app) as client:
        input_json = '{"text": "Hello world."}'

        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"authorization": "bearer invalid"},
        )

        assert response.status_code == 403


def test_config_not_changed(set_redis):
    with TestClient(app) as client:
        input_json = '{"text": "Hello world.", "config_hash": "foobar", "organization_config_hash": "foobaz"}'

        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )

        assert response.status_code == 200
        response_content = json.loads(response.content)
        assert "config_changed" not in response_content


def test_config_changed(set_redis):
    with TestClient(app) as client:
        input_json = '{"text": "Hello world.", "config_hash": "foo"}'

        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )

        assert response.status_code == 200
        response_content = json.loads(response.content)
        assert response_content["config_changed"] is True


def test_config_organization_changed(set_redis):
    with TestClient(app) as client:
        input_json = '{"text": "Hello world.", "organization_config_hash": "bar"}'

        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )

        assert response.status_code == 200
        response_content = json.loads(response.content)
        assert response_content["config_changed"] is True


@pytest.fixture
def set_redis():
    # test-missing-org@gmail.com
    user_object = {
        "id": "test-missing-org",
        "email": "test-missing-org@gmail.com",
        "plan": "none",
        "organization_id": "test-missing-org",
        "name": "Tests Missing Org",
        "config": {},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
        "notifications": 0,
    }

    user_object["term_replacements"] = parse_term_replacements(
        user_object["term_replacements"], context
    )
    context.redis.db.set(
        context.redis.get_user_id(user_object["email"]), json.dumps(user_object)
    )

    # 2_2@gmail.com
    user_object = {
        "id": "test-2_2",
        "email": "2_2@gmail.com",
        "plan": "witty_free",
        "organization_id": "test-2_2-org",
        "name": "Tests 2_2",
        "config": {},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
        "notifications": 0,
    }

    context.redis.db.set(
        context.redis.get_user_id(user_object["email"]), json.dumps(user_object)
    )

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Team 2_2",
        "plan": "witty_free",
        "trial_ends_at": "2024-04-09 14:52:15",
        "config": {},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
    }

    context.redis.db.set(organization_object["id"], json.dumps(organization_object))

    # free@gmail.com
    user_object = {
        "id": "test-free",
        "email": "free@gmail.com",
        "plan": "witty_free",
        "organization_id": "test-free-org",
        "name": "Tests Free",
        "config": {"categories": {}},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
        "notifications": 0,
    }

    context.redis.db.set(
        context.redis.get_user_id(user_object["email"]), json.dumps(user_object)
    )

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Free",
        "plan": "witty_free",
        "trial_ends_at": "2024-04-09 14:52:15",
        "config": {"categories": {}},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
    }

    context.redis.db.set(organization_object["id"], json.dumps(organization_object))

    # default@gmail.com
    user_object = {
        "id": "test-default",
        "email": "default@gmail.com",
        "plan": "witty_teams",
        "organization_id": "test-default-org",
        "name": "Tests Default",
        "config": {
            "categories": {
                "plain_language_advanced": {"value": False, "status": "force"},
            },
        },
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "notifications": 0,
        "config_hash": None,
        "team_analytics": False,
    }

    context.redis.db.set(
        context.redis.get_user_id(user_object["email"]), json.dumps(user_object)
    )

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

    context.redis.db.set(organization_object["id"], json.dumps(organization_object))

    # test@gmail.com
    user_object = {
        "id": "test-user",
        "email": "test@gmail.com",
        "plan": "witty_teams",
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
                "plain_language_advanced": {"value": False, "status": "force"},
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
            "deutsche Natur|de": {
                "alternatives": ["Deutsche Natur"],
                "word_type": "=",
                "explanation": {
                    "text": "capitalization",
                    "icon": None,
                    "url": None,
                },
                "lang": "de",
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

    user_object["term_replacements"] = parse_term_replacements(
        user_object["term_replacements"], context
    )
    context.redis.db.set(
        context.redis.get_user_id(user_object["email"]), json.dumps(user_object)
    )

    organization_object = {
        "id": user_object["organization_id"],
        "name": "Witty Works",
        "plan": "witty_teams",
        "config": {
            "store_context": {
                "value": True,
                "status": "force",
            },
            "llm_alternatives": {
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
            "force_categories": ["social-motive"],
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

    organization_object["term_replacements"] = parse_term_replacements(
        organization_object["term_replacements"], context
    )
    context.redis.db.set(organization_object["id"], json.dumps(organization_object))


@pytest.mark.parametrize(
    "test_false_positive_dir",
    get_dirs("tests/test_false_positive"),
)
def test_false_positive(test_false_positive_dir, snapshot, set_redis):
    with TestClient(app) as client:
        input_json = test_false_positive_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
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
    "test_witty_addons_dir",
    get_dirs("tests/test_witty_addons"),
)
def test_witty_addons(test_witty_addons_dir, snapshot, set_redis):
    with TestClient(app) as client:
        input_json = test_witty_addons_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_witty_addons_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_not_logged_in_dir",
    get_dirs("tests/test_not_logged_in"),
)
def test_not_logged_in(test_not_logged_in_dir, snapshot):
    with TestClient(app) as client:
        input_json = test_not_logged_in_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post("/v2.4/check", json=json.loads(input_json))
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_not_logged_in_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "test_logged_in_missing_org_dir",
    get_dirs("tests/test_logged_in_missing_org"),
)
def test_logged_in_missing_org(test_logged_in_missing_org_dir, snapshot, set_redis):
    with TestClient(app) as client:
        input_json = test_logged_in_missing_org_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test-missing-org@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_logged_in_missing_org_dir
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
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

        response = client.post(
            "/v2.0/auth", headers={"X-TESTING-AUTH": "missing@gmail.com"}
        )
        assert response.status_code == 403

        response = client.post(
            "/v2.0/auth", headers={"X-TESTING-AUTH": "2_2@gmail.com"}
        )
        assert response.status_code == 200
        # A stored `trial_ends_at` is ignored rather than reported on: the
        # dashboard still syncs one, and nothing here acts on it.
        assert "organization_trial_ends_at" not in response.json()

        response = client.post(
            "/v2.0/auth", headers={"X-TESTING-AUTH": "test@gmail.com"}
        )
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
        response = client.post(
            "/v2.0/auth", headers={"X-TESTING-AUTH": "default@gmail.com"}
        )
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
            headers={"Authorization": "Bearer " + tokens["third_party_token"]},
        )
        assert response.status_code == 403


def test_api_key_validation(set_redis):
    with TestClient(app) as client:
        # Invalid API key on auth should be forbidden
        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"x-key": "invalid"},
        )
        assert response.status_code == 403

        # Create a valid API key mapping via management endpoint
        api_key = "valid-api-key-123"
        email = "test@gmail.com"
        resp = client.post("/api_key", params={"api_key": api_key, "email": email})
        assert resp.status_code == 204

        # Valid API key on auth should pass
        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"x-key": api_key},
        )
        assert response.status_code == 200

        # Invalid API key for check endpoint: unauthenticated is allowed -> 200
        response = client.post(
            "/v2.4/check",
            json={"text": "Hallo Kunde"},
            headers={"x-key": "invalid"},
        )
        assert response.status_code == 200

        # Valid API key for check endpoint should also return 200
        response = client.post(
            "/v2.4/check",
            json={"text": "Hallo Kunde"},
            headers={"x-key": api_key},
        )
        assert response.status_code == 200

        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"Authorization": "Bearer " + tokens["azureadbc_valid_expired"]},
        )
        assert response.status_code == 403

        response = client.post(
            "/v2.4/check",
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_disable_categories_dir
        snapshot.assert_match(output, "output.json")


def test_validate_scope(set_redis):
    try:
        claims = get_unverified_token_claims_(tokens["azureadbc_valid_expired"])
        valid = validate_scope_("access_as_user", claims)
    except:
        valid = False

    assert valid is not False

    try:
        claims = get_unverified_token_claims_(tokens["other_valid_expired"])
        valid = validate_scope_("access_as_user", claims)
    except:
        valid = False

    assert valid is False


def test_token(set_redis):
    try:
        token = get_token_("")
    except AuthError as e:
        token = False

    assert token is False

    try:
        token = get_token_("invalid")
    except AuthError as e:
        token = False

    assert token is False

    token = get_token_("bearer invalid")
    assert token == "invalid"

    token = get_token_("bearer " + tokens["azureadbc_valid_expired"])
    assert token == tokens["azureadbc_valid_expired"]


def test_token_claims(set_redis):
    claims = get_unverified_token_claims_(tokens["azureadbc_valid_expired"])

    assert claims is not False


# test overwriting user configuration by organization forced rules
@pytest.mark.asyncio
async def test_fetch_configs_for_request(set_redis):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
        "config": {
            "store_context": False,
            "llm_alternatives": False,
            "primary_language": "de-DE",
            "preferred_languages": "de",
            "preferred_variants": "de-DE",
            "german_gender_ending": "/in",
            "gendered_roles_format": "inclusive_gender",
        },
    }
    test_request = CheckRequestIn(**request_data)
    await fetch_configs_for_request(test_request, "test@gmail.com", context)
    assert hasattr(test_request.config, "store_context")
    assert test_request.config.store_context is True
    assert hasattr(test_request.config, "llm_alternatives")
    assert test_request.config.llm_alternatives is True
    assert test_request.config.preferred_variants == ["en-GB"]
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test not overwriting user configuration by organization suggestion/default rules


@pytest.mark.asyncio
async def test_fetch_user_rules_suggestion(set_redis):
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
    test_request = CheckRequestIn(**request_data)
    await fetch_configs_for_request(test_request, "non_existant@gmail.com", context)
    assert test_request.config.store_context is True
    assert test_request.config.llm_alternatives is False
    assert test_request.config.primary_language == "de-DE"
    assert test_request.config.preferred_languages == ["de"]
    assert test_request.config.preferred_variants == ["de-DE"]
    assert test_request.config.german_gender_ending == "/in"
    assert test_request.config.gendered_roles_format == "inclusive_gender"


# test user not set any parameters, but organization did


@pytest.mark.asyncio
async def test_set_organization_rules(set_redis):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = CheckRequestIn(**request_data)
    await fetch_configs_for_request(test_request, "test@gmail.com", context)
    assert test_request.config.store_context is True
    assert test_request.config.llm_alternatives is True
    assert test_request.config.preferred_variants == ["en-GB"]
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test user and organization didn't set any rules


@pytest.mark.asyncio
async def test_set_default_rules():
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = CheckRequestIn(**request_data)

    await fetch_configs_for_request(test_request, "non_existant@gmail.com", context)
    assert test_request.config.store_context is True
    assert test_request.config.llm_alternatives is False
    assert test_request.config.primary_language is None
    assert test_request.config.preferred_languages == [
        LangWithAutoType.EN,
        LangWithAutoType.DE,
        LangWithAutoType.FR,
    ]
    assert test_request.config.preferred_variants == [
        LangWithAutoType.enUS,
        LangWithAutoType.deDE,
        LangWithAutoType.frFR,
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
            "llm_alternatives": {
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
            "llm_alternatives": {
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

    with TestClient(app) as client:
        # check user is missing
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 404

        # create user rules
        response = client.post("/user/configs", json=user_request_data)
        assert response.status_code == 204

        # update user rules
        user_request_data["config"]["gendered_roles_format"]["value"] = "none"
        response = client.post("/user/configs", json=user_request_data)
        assert response.status_code == 204

        # check user is missing
        response = client.get("/user/configs?email=bar")
        assert response.status_code == 404

        # check user exists but org missing
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 404
        assert response.content == b'{"detail":"Organization configs not found"}'

        # check organization is missing
        response = client.get(
            "/organization/configs?organization_id=" + organization_request_data["id"]
        )
        assert response.status_code == 404

        # check organization is created
        response = client.post("/organization/configs", json=organization_request_data)
        assert response.status_code == 204

        response = client.get(
            "/organization/configs?organization_id=" + organization_request_data["id"]
        )
        assert_rules(response, organization_request_data)

        # check user exists
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert_rules(response, user_request_data)

        # check user is missing can be deleted
        response = client.delete("/user/configs?email=foobar")
        assert response.status_code == 204

        # check user is deleted
        response = client.delete("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 204

        # check organization is updated
        organization_request_data["config"]["gendered_roles_format"]["value"] = "both"
        response = client.post("/organization/configs", json=organization_request_data)
        assert response.status_code == 204

        response = client.get(
            "/organization/configs?organization_id=" + organization_request_data["id"]
        )
        assert_rules(response, organization_request_data)

        # check user is missing
        response = client.get("/user/configs?email=bar")
        assert response.status_code == 404

        # check user is still missing
        response = client.get("/user/configs?email=" + user_request_data["email"])
        assert response.status_code == 404

        # check user is created
        response = client.post("/user/configs", json=user_request_data)
        assert response.status_code == 204

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
        assert response.content == b'{"detail":"Organization configs not found"}'


def test_user_config_sync_inklusivum(snapshot):
    """The dashboard sync path for the Inklusivum ending.

    The gender-ending fixtures pass the config inline with each check; the
    dashboard instead stores it via POST /user/configs. This covers that
    round-trip: a dashboard-shaped payload with german_gender_ending "de-e"
    is stored, and a subsequent check without any inline config must come
    back Inklusivum-formatted (Jedey Expertere, ensen - not Expert*in).
    """
    user_request_data = {
        "id": "test-config-sync-inklusivum",
        "email": "config-sync-inklusivum@gmail.com",
        "name": "Tests Config Sync Inklusivum",
        "organization_id": None,
        "config": {
            "german_gender_ending": {"value": "de-e", "status": "force"},
            "gendered_roles_format": {"value": "inclusive_gender", "status": "force"},
            "preferred_variants": {"value": ["de-DE", "en-US"], "status": "suggestion"},
            "french_gender_separator": {"value": "·", "status": "suggestion"},
            "show_inspiration_alternatives": {"value": True, "status": "suggestion"},
            "categories": {},
        },
        "false_positives": [],
        "domains": {"list": [], "type": "deny"},
        "notifications": 5,
        "config_hash": "test-config-sync-inklusivum-hash",
        "sync_date": "2026-08-07 12:00:00",
    }

    with TestClient(app) as client:
        response = client.post("/user/configs", json=user_request_data)
        assert response.status_code == 204

        response = client.post(
            "/v2.4/check",
            json={
                "text": "Jeder Experte weiß das. Die Lehrerin gibt dem Schüler"
                " den Stift. Wir suchen einen Mitarbeiter und seinen Kollegen."
            },
            headers={"X-TESTING-AUTH": user_request_data["email"]},
        )
        assert response.status_code == 200

        # The stored ending formats the suggestions; nothing may fall back to
        # a separator ending like Expert*in.
        body = response.json()
        texts = [
            alternative["text"]
            for result in body["results"]
            for alternative in result["alternatives"]
        ]
        assert not any("*" in text for text in texts)

        # Gendered findings carry the Inklusivum logo from
        # config_options.json; findings from other categories keep theirs.
        logo = "https://www.witty.works/assets/media/vgd-icon-bunt.svg"
        by_subcategory = {result["subcategory"]: result for result in body["results"]}
        assert by_subcategory["titles"]["explanation"]["icon_image"] == logo
        assert by_subcategory["function"]["explanation"]["icon_image"] == logo
        assert (
            by_subcategory["anglicism_advanced"]["explanation"].get("icon_image")
            != logo
        )

        # output must be string
        output = json.dumps(body, sort_keys=True, indent=4, ensure_ascii=False)
        # Snapshot the return value.
        snapshot.snapshot_dir = "tests/test_user_config_sync/test_inklusivum"
        snapshot.assert_match(output, "output.json")


def test_api_key_get_missing():
    """GET /api_key should return 404 for unknown keys."""
    with TestClient(app) as client:
        response = client.get("/api_key", params={"api_key": "missing-key-123"})
        # Endpoint is defined with 404 response on missing key
        assert response.status_code == 404


def test_api_key_create_fetch_delete(set_redis):
    """POST/GET/DELETE flow for /api_key endpoints."""
    api_key = "test-api-key-123"
    email = "test@gmail.com"

    with TestClient(app) as client:
        # Ensure it's not there first
        resp = client.get("/api_key", params={"api_key": api_key})
        assert resp.status_code == 404

        # Create mapping
        resp = client.post("/api_key", params={"api_key": api_key, "email": email})
        assert resp.status_code == 204

        # Fetch mapping
        resp = client.get("/api_key", params={"api_key": api_key})
        # The operation is defined with 204 status; presence is asserted via Redis state
        assert resp.status_code == 204

        # Verify Redis contains the mapping
        stored = context.redis.db.get("api_key:" + api_key)
        assert stored == email

        # Delete mapping
        resp = client.delete("/api_key", params={"api_key": api_key})
        assert resp.status_code == 204

        # Ensure it's gone
        resp = client.get("/api_key", params={"api_key": api_key})
        assert resp.status_code == 404


def test_rule_debug():
    with TestClient(app) as client:
        request_data = {
            "text": "She has special needs",
            "lang": "en",
            "lemma": "have special need",
            "subcategories": ["corporate_rules"],
            "word_types": [
                {"word_type": "v", "lower_case": True, "lemmatize": True},
                {"word_type": "a", "lower_case": True, "lemmatize": True},
                {"word_type": "n", "lower_case": True, "lemmatize": True},
            ],
            "alternatives": [
                {
                    "lemma": "foo",
                    "words": ("foo",),
                },
                {
                    "lemma": "bar",
                    "words": ("bar",),
                },
                {
                    "lemma": "ding",
                    "words": ("ding",),
                    "label": "dong",
                },
            ],
        }
        response = client.post("/debug/rule", json=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = [
            {
                "text": "has special needs",
                "text_id": "test",
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
                "explanation": {
                    "text": "",
                    "long_text": "",
                    "icon": "❗",
                },
                "gravity": 0.9,
            }
        ]

        assert response_content == expected


def test_rule_patterns():
    with TestClient(app) as client:
        request_data = {
            "text": "Du arbeitest sehr sehr langsam",
            "lang": "de",
            "lemma": "langsam",
            "pattern": "v|a*|l",
            "label": "bar",
            "subcategories": ["corporate_rules"],
            "word_types": [
                {"word_type": "a", "lower_case": True, "lemmatize": True},
            ],
            "alternatives": [
                {
                    "lemma": "foo",
                    "words": ("foo",),
                }
            ],
        }
        response = client.post("/debug/rule", json=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = [
            {
                "text": "langsam",
                "text_id": "test",
                "context": "Du arbeitest sehr sehr langsam",
                "category": "corporate_rules",
                "subcategory": "corporate_rules",
                "start": 23,
                "end": 30,
                "alternatives": [{"text": "foo"}],
                "label": "Wörterbuch",
                "explanation": {
                    "text": "",
                    "long_text": "",
                    "icon": "❗",
                    "context": "bar",
                },
                "gravity": 0.9,
            }
        ]

        assert response_content == expected

        request_data = {
            "text": "Wir suchen super schnelle Entwickler unter 30",
            "lang": "de",
            "lemma": "unter",
            "pattern": "a*|n|l|card",
            "is_pattern_match": 1,
            "label": "bar",
            "subcategories": ["corporate_rules"],
            "word_types": [
                {"word_type": "", "lower_case": True, "lemmatize": True},
            ],
            "alternatives": [],
        }
        response = client.post("/debug/rule", json=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = [
            {
                "text": "super schnelle Entwickler unter 30",
                "text_id": "test",
                "context": "Wir suchen super schnelle Entwickler unter <NUMBER>",
                "category": "corporate_rules",
                "subcategory": "corporate_rules",
                "start": 11,
                "end": 45,
                "alternatives": [],
                "label": "Wörterbuch",
                "explanation": {
                    "text": "",
                    "long_text": "",
                    "icon": "❗",
                    "context": "bar",
                },
                "gravity": 0.9,
            }
        ]

        assert response_content == expected


def test_rule_debug_gendered_declension_fallback():
    # Gendered pairs whose declensions the nouns DB does not carry are
    # synthesized for the regular patterns (app.nouns.synthesize_gendered_pair)
    # instead of bailing with "Declension ... missing" and no alternatives.
    with TestClient(app) as client:
        # Weak masculine n-declension: masculine oblique forms end in -n.
        request_data = {
            "text": "Der Guatemalteke kam am Morgen.",
            "lang": "de",
            "lemma": "Guatemalteke",
            "subcategories": ["titles"],
            "word_types": [
                {"word_type": "n", "lower_case": False, "lemmatize": True},
            ],
            "alternatives": [
                {
                    "lemma": "Guatemalteke~Guatemaltekin",
                    "is_gendered_noun": True,
                    "word_types": [
                        {"word_type": "n", "lower_case": False, "lemmatize": True},
                    ],
                },
            ],
        }
        response = client.post("/debug/rule", json=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        assert len(response_content) == 1
        finding = response_content[0]
        assert finding["text"] == "Guatemalteke"
        assert finding["subcategory"] == "titles"
        assert finding["alternatives"] == [
            {
                "text": "Guatemaltek*in",
                "male_form": "Guatemalteken",
                "female_form": "Guatemaltekin",
                "gender_role": "inclusive_gender",
            },
            {
                "text": "Guatemaltekin/Guatemalteken",
                "male_form": "Guatemalteken",
                "female_form": "Guatemaltekin",
                "gender_role": "binary_gender",
            },
        ]

        # -er class: masculine plural equals the base form.
        request_data = {
            "text": "Die Temposünder werden verwarnt.",
            "lang": "de",
            "lemma": "Temposünder",
            "subcategories": ["titles"],
            "word_types": [
                {"word_type": "n", "lower_case": False, "lemmatize": True},
            ],
            "alternatives": [
                {
                    "lemma": "Temposünder~Temposünderin",
                    "is_gendered_noun": True,
                    "word_types": [
                        {"word_type": "n", "lower_case": False, "lemmatize": True},
                    ],
                },
            ],
        }
        response = client.post("/debug/rule", json=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        assert len(response_content) == 1
        finding = response_content[0]
        assert finding["text"] == "Temposünder"
        assert finding["alternatives"] == [
            {
                "text": "Temposünder*innen",
                "male_form": "Temposünder",
                "female_form": "Temposünderinnen",
                "gender_role": "inclusive_gender",
            },
            {
                "text": "Temposünderinnen und Temposünder",
                "male_form": "Temposünder",
                "female_form": "Temposünderinnen",
                "gender_role": "binary_gender",
            },
        ]


@pytest.mark.parametrize(
    "spacy_analysis_dir",
    get_dirs("tests/test_spacy_analysis"),
)
def test_spacy_analysis(spacy_analysis_dir, snapshot):
    """Token-level snapshot of the spaCy analysis (docs/spacy-review.md, Phase 0).

    Captures word_type, lemma, is_singular plus the raw tag/pos/morph/dep per
    token, so changes to models or the analysis pipeline show up as reviewable
    token diffs instead of only opaque end-to-end rule changes.
    """
    with TestClient(app) as client:
        input_json = json.loads(
            spacy_analysis_dir.joinpath("input.json").read_text()
        )
        response = client.get("/debug/spacy", params=input_json)
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = spacy_analysis_dir
        snapshot.assert_match(output, "output.json")


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
            {"auto-detected word type": "emoji|~pron|~|adv|a|n||||emoji"},
            {
                "text": "👩🏻‍🚒",
                "lemma": "👩🏻‍🚒",
                "word_type": "emoji",
                "is_singular": True,
                "ner": "",
            },
            {
                "text": "Das",
                "lemma": "der",
                "word_type": "pron",
                "is_singular": True,
                "ner": "",
            },
            {
                "text": "ist",
                "lemma": "sein",
                "word_type": "",
                "is_singular": True,
                "ner": "",
            },
            {
                "text": "sehr",
                "lemma": "sehr",
                "word_type": "adv",
                "is_singular": None,
                "ner": "",
            },
            {
                "text": "ehrgeizig",
                "lemma": "ehrgeizig",
                "word_type": "a",
                "is_singular": None,
                "ner": "",
            },
            {
                "text": "Herr",
                "lemma": "Herr",
                "word_type": "n",
                "is_singular": True,
                "ner": "PER",
            },
            {
                "text": "Müller",
                "lemma": "Müller",
                "word_type": "",
                "is_singular": True,
                "ner": "PER",
            },
            {
                "text": "in",
                "lemma": "in",
                "word_type": "",
                "is_singular": None,
                "ner": "",
            },
            {
                "text": "London",
                "lemma": "London",
                "word_type": "",
                "is_singular": True,
                "ner": "LOC",
            },
            {
                "text": "😃",
                "lemma": "😃",
                "word_type": "emoji",
                "is_singular": False,
                "ner": "",
            },
        ]

        assert response_content == expected

        request_data["detailed"] = True

        response = client.get("/debug/spacy", params=request_data)
        assert response.status_code == 200
        response_content = json.loads(response.content)

        expected = [
            {"auto-detected word type": "emoji|~pron|~|adv|a|n||||emoji"},
            {
                "noun chunks": [
                    {"text": "👩🏻‍🚒", "start": 0, "end": 1},
                    {"text": "Das", "start": 1, "end": 2},
                    {"text": "Herr Müller", "start": 5, "end": 7},
                    {"text": "London", "start": 8, "end": 9},
                    {"text": "😃", "start": 9, "end": 10},
                ]
            },
            {
                "text": "👩🏻‍🚒",
                "lemma": "👩🏻‍🚒",
                "word_type": "emoji",
                "is_singular": True,
                "ner": "",
                "start": 0,
                "whitespace": " ",
                "emoji_desc": "woman firefighter light skin tone",
                "is_emoji": True,
                "morph": {"Case": "Nom", "Gender": "Fem", "Number": "Sing"},
                "tag": "NE",
                "pos": "PROPN",
                "dep": "ROOT",
                "head": "👩🏻‍🚒",
                "dependent": None,
                "children": [],
            },
            {
                "text": "Das",
                "lemma": "der",
                "word_type": "pron",
                "is_singular": True,
                "ner": "",
                "start": 5,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {
                    "Case": "Nom",
                    "Gender": "Neut",
                    "Number": "Sing",
                    "PronType": "Dem",
                },
                "tag": "PDS",
                "pos": "PRON",
                "dep": "sb",
                "head": "ist",
                "dependent": None,
                "children": [
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "ist",
                "lemma": "sein",
                "word_type": "",
                "is_singular": True,
                "ner": "",
                "start": 9,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {
                    "Mood": "Ind",
                    "Number": "Sing",
                    "Person": "3",
                    "Tense": "Pres",
                    "VerbForm": "Fin",
                },
                "tag": "VAFIN",
                "pos": "AUX",
                "dep": "ROOT",
                "head": "ist",
                "dependent": None,
                "children": [],
            },
            {
                "text": "sehr",
                "lemma": "sehr",
                "word_type": "adv",
                "is_singular": None,
                "ner": "",
                "start": 13,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {},
                "tag": "ADV",
                "pos": "ADV",
                "dep": "mo",
                "head": "ehrgeizig",
                "dependent": None,
                "children": [
                    {"dep": "mo", "token": "sehr", "ner": ""},
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "ehrgeizig",
                "lemma": "ehrgeizig",
                "word_type": "a",
                "is_singular": None,
                "ner": "",
                "start": 18,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {"Degree": "Pos"},
                "tag": "ADJD",
                "pos": "ADV",
                "dep": "pd",
                "head": "ist",
                "dependent": None,
                "children": [
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "Herr",
                "lemma": "Herr",
                "word_type": "n",
                "is_singular": True,
                "ner": "PER",
                "start": 28,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {"Case": "Nom", "Gender": "Masc", "Number": "Sing"},
                "tag": "NN",
                "pos": "NOUN",
                "dep": "pd",
                "head": "ist",
                "dependent": None,
                "children": [
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "Müller",
                "lemma": "Müller",
                "word_type": "",
                "is_singular": True,
                "ner": "PER",
                "start": 33,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {"Case": "Nom", "Gender": "Masc", "Number": "Sing"},
                "tag": "NE",
                "pos": "PROPN",
                "dep": "nk",
                "head": "Herr",
                "dependent": None,
                "children": [
                    {"dep": "nk", "token": "Müller", "ner": "PER"},
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "in",
                "lemma": "in",
                "word_type": "",
                "is_singular": None,
                "ner": "",
                "start": 40,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {},
                "tag": "APPR",
                "pos": "ADP",
                "dep": "mo",
                "head": "ist",
                "dependent": None,
                "children": [
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "London",
                "lemma": "London",
                "word_type": "",
                "is_singular": True,
                "ner": "LOC",
                "start": 43,
                "whitespace": " ",
                "emoji_desc": None,
                "is_emoji": False,
                "morph": {"Case": "Dat", "Gender": "Neut", "Number": "Sing"},
                "tag": "NE",
                "pos": "PROPN",
                "dep": "nk",
                "head": "in",
                "dependent": None,
                "children": [
                    {"dep": "nk", "token": "London", "ner": "LOC"},
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
            {
                "text": "😃",
                "lemma": "😃",
                "word_type": "emoji",
                "is_singular": False,
                "ner": "",
                "start": 50,
                "whitespace": "",
                "emoji_desc": "grinning face with big eyes",
                "is_emoji": True,
                "morph": {"Case": "Acc", "Gender": "Neut", "Number": "Plur"},
                "tag": "NN",
                "pos": "NOUN",
                "dep": "pd",
                "head": "ist",
                "dependent": None,
                "children": [
                    {"dep": "sb", "token": "Das", "ner": ""},
                    {"dep": "pd", "token": "ehrgeizig", "ner": ""},
                    {"dep": "pd", "token": "Herr", "ner": "PER"},
                    {"dep": "mo", "token": "in", "ner": ""},
                    {"dep": "pd", "token": "😃", "ner": ""},
                ],
            },
        ]

        assert response_content == expected


@pytest.mark.parametrize(
    "lemma_case_dir",
    get_dirs("tests/test_lemmatizers"),
)
def test_lemmatizer(lemma_case_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = lemma_case_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
    "test_not_for_people_dir",
    get_dirs("tests/test_not_for_people"),
)
def test_not_for_people(test_not_for_people_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = test_not_for_people_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = test_not_for_people_dir
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
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
    "context_checker_dir",
    get_dirs("tests/test_context_checker"),
)
@pytest.mark.skipif(
    not context.settings.context_checker_local,
    reason="Skipping context checker tests: local models are not enabled",
)
def test_context_checker(context_checker_dir, snapshot, set_redis):
    """
    Test that context checker correctly identifies false positives vs genuine matches.

    The context checker uses SetFit models (or remote API) to analyze whether
    flagged words are used in problematic contexts or are false positives.

    Examples:
    - "fossil fuel industry" - false positive (scientific/technical context)
    - "you are such a fossil" - genuine match (ageist insult)
    - "Die Firma ist unabhängig" - false positive (company independence)
    - "Sie ist sehr unabhängig" - genuine match (gender stereotype)
    """
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = context_checker_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = context_checker_dir
        snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "plain_language_dir",
    get_dirs("tests/test_plain_language"),
)
def test_plain_language(plain_language_dir, snapshot, set_redis):
    with TestClient(app) as client:
        # Read input files from the case directory.
        input_json = plain_language_dir.joinpath("input.json").read_text()
        # Call the tested endpoint.
        response = client.post(
            "/v2.4/check",
            json=json.loads(input_json),
            headers={"X-TESTING-AUTH": "free@gmail.com"},
        )
        assert response.status_code == 200
        # output must be string
        output = json.dumps(
            response.json(), sort_keys=True, indent=4, ensure_ascii=False
        )
        # Snapshot the return value.
        snapshot.snapshot_dir = plain_language_dir
        snapshot.assert_match(output, "output.json")


@pytest.fixture
def dashboard_sso(request):
    """Register a dashboard issuer and pre-seed its verification key.

    The RSA PEM is written straight into the cache `get_rsa_key` reads, so the
    test never reaches out for the JWKS document — the fetch path itself is
    shared with the Microsoft issuers and covered by their tests.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()

    def to_base64_url(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    kid = "test-dashboard-kid"
    context.redis.db.set(
        "rsa_pem:" + kid,
        convert_to_pem(to_base64_url(numbers.n), to_base64_url(numbers.e)),
    )

    previous = context.settings.sso_configs.get("dashboard")
    context.settings.sso_configs["dashboard"] = {
        "client_id": "1",
        "jwks_url": "https://dashboard.example.com/.well-known/jwks.json",
        "issuer": None,
        "expected_scope": None,
    }

    def issue(**overrides) -> str:
        now = int(time.time())
        claims = {
            "aud": "1",
            "jti": "1234",
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
            "sub": "1",
            "scopes": [],
            "email": "test@gmail.com",
            "preferred_username": "test@gmail.com",
        }
        claims.update(overrides)

        return jwt.encode(
            claims,
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            algorithm="RS256",
            headers={"kid": kid},
        )

    yield issue

    context.redis.db.delete("rsa_pem:" + kid)
    if previous is None:
        del context.settings.sso_configs["dashboard"]
    else:  # pragma: no cover
        context.settings.sso_configs["dashboard"] = previous


def test_dashboard_token(dashboard_sso, set_redis):
    """A Passport access token maps to the user it names."""
    with TestClient(app) as client:
        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"Authorization": "Bearer " + dashboard_sso()},
        )
        assert response.status_code == 200
        assert response.json()["id"] == "test-user"


def test_dashboard_token_rejections(dashboard_sso, set_redis):
    """Expired, wrong-audience and unsigned variants are all refused."""
    with TestClient(app) as client:
        expired = dashboard_sso(iat=1, nbf=1, exp=2)
        response = client.post(
            "/v2.0/auth", json={}, headers={"Authorization": "Bearer " + expired}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Token error: The token has expired"

        # A different client id belongs to no configured issuer at all.
        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"Authorization": "Bearer " + dashboard_sso(aud="2")},
        )
        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "Token provided did not map to a valid client ID"
        )

        # Same claims, signed with a key the issuer does not publish.
        tampered = jwt.encode(
            get_unverified_token_claims_(dashboard_sso()),
            "secret",
            algorithm="HS256",
            headers={"kid": "test-dashboard-kid"},
        )
        response = client.post(
            "/v2.0/auth", json={}, headers={"Authorization": "Bearer " + tampered}
        )
        assert response.status_code == 403


def test_dashboard_token_issuer_enforced(dashboard_sso, set_redis):
    """Configuring an issuer makes a token without an `iss` claim invalid."""
    context.settings.sso_configs["dashboard"][
        "issuer"
    ] = "https://dashboard.example.com"

    with TestClient(app) as client:
        response = client.post(
            "/v2.0/auth",
            json={},
            headers={"Authorization": "Bearer " + dashboard_sso()},
        )
        assert response.status_code == 403

        response = client.post(
            "/v2.0/auth",
            json={},
            headers={
                "Authorization": "Bearer "
                + dashboard_sso(iss="https://dashboard.example.com")
            },
        )
        assert response.status_code == 200


@pytest.fixture
def standalone_settings():
    """Run the API the way a deployment without a dashboard would."""
    previous = (
        context.settings.default_user_config_enabled,
        context.settings.client_config_enabled,
    )
    context.settings.default_user_config_enabled = True
    context.settings.client_config_enabled = True

    yield context.settings

    (
        context.settings.default_user_config_enabled,
        context.settings.client_config_enabled,
    ) = previous


def test_auth_without_dashboard_config(standalone_settings):
    """An API key for an unsynced user still resolves to a usable config."""
    api_key = "standalone-api-key"
    email = "nobody-synced-me@example.com"

    with TestClient(app) as client:
        context.redis.set_api_key(api_key, email)

        response = client.post("/v2.0/auth", json={}, headers={"x-key": api_key})
        assert response.status_code == 200

        config = response.json()
        # No organisation exists to belong to, and nulls are stripped from the
        # response, so the key is absent rather than null.
        assert "organization_id" not in config
        assert config["config_hash"]

        # Stable across calls, so a client can tell a stale copy from a fresh one.
        again = client.post("/v2.0/auth", json={}, headers={"x-key": api_key})
        assert again.json()["config_hash"] == config["config_hash"]

        # And the check endpoint works for the same key.
        response = client.post(
            "/v2.4/check",
            json={"text": "Wir suchen einen Ninja Programmierer."},
            headers={"x-key": api_key},
        )
        assert response.status_code == 200
        assert len(response.json()["results"])

        context.redis.delete_api_key(api_key)


@pytest.mark.asyncio
async def test_default_user_config_flags(standalone_settings):
    """The configured defaults take effect whether or not clients may set them."""
    email = "nobody-synced-me@example.com"
    standalone_settings.default_user_llm_alternatives = True

    try:
        # Clients may set the flags, so the default is only a starting point.
        request_in = CheckRequestIn(text="Hello world.")
        await fetch_configs_for_request(request_in, email, context)
        assert request_in.config.llm_alternatives is True

        request_in = CheckRequestIn(
            text="Hello world.", config={"llm_alternatives": False}
        )
        await fetch_configs_for_request(request_in, email, context)
        assert request_in.config.llm_alternatives is False

        # Clients may not, so the default is the last word.
        standalone_settings.client_config_enabled = False

        request_in = CheckRequestIn(
            text="Hello world.", config={"llm_alternatives": False}
        )
        await fetch_configs_for_request(request_in, email, context)
        assert request_in.config.llm_alternatives is True
    finally:
        standalone_settings.default_user_llm_alternatives = False


def test_auth_without_dashboard_config_disabled():
    """Without the flag an unsynced user keeps being rejected."""
    api_key = "standalone-api-key-off"
    email = "nobody-synced-me@example.com"

    with TestClient(app) as client:
        context.redis.set_api_key(api_key, email)

        response = client.post("/v2.0/auth", json={}, headers={"x-key": api_key})
        assert response.status_code == 403

        context.redis.delete_api_key(api_key)


@pytest.mark.asyncio
async def test_client_settable_config(standalone_settings, set_redis):
    """`store_context` and `llm_alternatives` follow the request when allowed."""
    request_in = CheckRequestIn(
        text="Hello world.",
        config={"store_context": False, "llm_alternatives": True},
    )
    # default@gmail.com's organisation forces neither of the two.
    await fetch_configs_for_request(request_in, "default@gmail.com", context)

    assert request_in.config.store_context is False
    assert request_in.config.llm_alternatives is True

    # An organisation that does force them keeps the last word.
    request_in = CheckRequestIn(
        text="Hello world.",
        config={"store_context": False, "llm_alternatives": False},
    )
    await fetch_configs_for_request(request_in, "test@gmail.com", context)

    assert request_in.config.store_context is True
    assert request_in.config.llm_alternatives is True


@pytest.mark.asyncio
async def test_client_settable_config_disabled(set_redis):
    """With the flag off the server keeps deciding both."""
    request_in = CheckRequestIn(
        text="Hello world.",
        config={"store_context": False, "llm_alternatives": True},
    )
    await fetch_configs_for_request(request_in, "default@gmail.com", context)

    assert request_in.config.store_context is True
    assert request_in.config.llm_alternatives is False


def test_categories():
    """The category list is public and cacheable."""
    with TestClient(app) as client:
        response = client.get("/v2.0/categories")
        assert response.status_code == 200
        # The security middleware must not have clobbered this with no-cache.
        assert response.headers["Cache-Control"] == "public, max-age=3600"

        payload = response.json()
        categories = {category["key"]: category for category in payload["categories"]}

        # Every reported key is one the check endpoint accepts as disabled.
        assert set(categories) <= set(get_category_keys())

        assert categories["sexism"]["parent"] == "gender-orientation"
        assert categories["sexism"]["advanced_key"] == "sexism_advanced"
        assert categories["orthography"]["advanced_key"] is None
        assert categories["sexism"]["label"] == "Sexism"

        groups = {group["key"]: group for group in payload["groups"]}
        assert set(category["parent"] for category in categories.values()) == set(
            groups
        )
        assert groups["gender-orientation"]["label"] == "Gender + Orientation"

        response = client.get("/v2.0/categories", params={"locale": "de-DE"})
        assert response.status_code == 200

        german = {
            category["key"]: category for category in response.json()["categories"]
        }
        assert set(german) == set(categories)
        assert german["sexism"]["label"] not in (
            None,
            "",
            categories["sexism"]["label"],
        )


def test_require_auth_off():
    """A deployment can choose to check text for anyone who asks."""
    text = {"text": "Wir suchen einen Ninja Programmierer."}

    with TestClient(app) as client:
        # The default: no user, no results, but still a 200 so a client that has
        # been signed out keeps working.
        response = client.post("/v2.4/check", json=text)
        assert response.status_code == 200
        assert response.json()["results"] == []

        context.settings.require_auth = False
        try:
            response = client.post("/v2.4/check", json=text)
            assert response.status_code == 200
            assert len(response.json()["results"])
        finally:
            context.settings.require_auth = True


def test_management_auth():
    """The endpoints that mint credentials are closed unless told otherwise."""
    with TestClient(app) as client:
        context.settings.management_auth_enabled = True
        try:
            response = client.post(
                "/api_key", params={"api_key": "should-not-exist", "email": "a@b.c"}
            )
            assert response.status_code == 401

            # The settings object carries every secret the deployment holds.
            assert client.get("/settings").status_code == 401

            # `user_email` is a query parameter here, so the caller picks whose
            # config applies and whose LLM budget is spent.
            response = client.post(
                "/v1.0/prompt",
                params={"user_email": "test@gmail.com"},
                json={"text": "Hello world."},
            )
            assert response.status_code == 401

            # The docs switch is a separate decision and stays where it was.
            assert context.settings.api_docs_auth_enabled is False
        finally:
            context.settings.management_auth_enabled = False

        assert context.redis.get_api_key_email("should-not-exist") is None


@pytest.fixture
def llm_access():
    """Set the LLM access policy for one test and put it back afterwards."""
    previous = (
        context.settings.llm_access,
        context.settings.llm_allowed_users,
        context.settings.llm_model,
    )

    def set_access(access, allowed_users=None):
        context.settings.llm_access = access
        context.settings.llm_allowed_users = allowed_users or []
        # A deployment with no model configured has no LLM whatever the policy
        # says, so naming one is what makes the policy observable at all.
        context.settings.llm_model = "bedrock/some.model"

        return context.settings

    yield set_access

    (
        context.settings.llm_access,
        context.settings.llm_allowed_users,
        context.settings.llm_model,
    ) = previous


@pytest.mark.asyncio
async def test_llm_access_disabled(llm_access, standalone_settings, set_redis):
    """Nothing turns LLM alternatives on once the operator says no."""
    llm_access(LlmAccessType.DISABLED)

    # Not the client...
    request_in = CheckRequestIn(text="Hello world.", config={"llm_alternatives": True})
    await fetch_configs_for_request(request_in, "default@gmail.com", context)
    assert request_in.config.llm_alternatives is False

    # ...and not an organisation that forces them on either.
    request_in = CheckRequestIn(text="Hello world.")
    await fetch_configs_for_request(request_in, "test@gmail.com", context)
    assert request_in.config.llm_alternatives is False

    # Nor the debug routes, which resolve no user at all.
    assert (
        debug_configs(CheckRequestIn(text="Hello world."), context.settings)[
            "llm_alternatives"
        ]["value"]
        is False
    )


@pytest.mark.asyncio
async def test_llm_access_users(llm_access, standalone_settings, set_redis):
    """`users` allows whoever the request resolved to, or only the named ones."""
    settings = llm_access(LlmAccessType.USERS)

    request_in = CheckRequestIn(text="Hello world.", config={"llm_alternatives": True})
    await fetch_configs_for_request(request_in, "default@gmail.com", context)
    assert request_in.config.llm_alternatives is True

    # No user resolved, so there is nobody to allow.
    request_in = CheckRequestIn(text="Hello world.", config={"llm_alternatives": True})
    await fetch_configs_for_request(request_in, None, context)
    assert request_in.config.llm_alternatives is False

    # An allowlist narrows it to the named emails, matched case-insensitively.
    llm_access(LlmAccessType.USERS, ["Default@Gmail.com"])

    request_in = CheckRequestIn(text="Hello world.", config={"llm_alternatives": True})
    await fetch_configs_for_request(request_in, "default@gmail.com", context)
    assert request_in.config.llm_alternatives is True

    # test@gmail.com's organisation forces them on, and still does not get them.
    request_in = CheckRequestIn(text="Hello world.")
    await fetch_configs_for_request(request_in, "test@gmail.com", context)
    assert request_in.config.llm_alternatives is False

    assert settings.llm_allowed_users == ["Default@Gmail.com"]


@pytest.mark.asyncio
async def test_llm_access_everyone(llm_access, standalone_settings):
    """`everyone` covers requests that resolved to no user at all."""
    llm_access(LlmAccessType.EVERYONE)

    request_in = CheckRequestIn(text="Hello world.", config={"llm_alternatives": True})
    await fetch_configs_for_request(request_in, None, context)
    assert request_in.config.llm_alternatives is True

    # Still opt-in: the policy permits the spend, it does not ask for it.
    request_in = CheckRequestIn(text="Hello world.")
    await fetch_configs_for_request(request_in, None, context)
    assert request_in.config.llm_alternatives is False


def test_llm_access_rephrase(llm_access, set_redis):
    """The policy reaches the endpoint that actually spends the tokens."""
    llm_access(LlmAccessType.DISABLED)

    with TestClient(app) as client:
        response = client.post(
            "/v1.0/rephrase",
            json={
                "sentence": "The chairman called.",
                "text": "The chairman called.",
                "start": 0,
                "alternatives": [],
                "lang": "en",
            },
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )
        # test@gmail.com's organisation forces llm_alternatives on, so without
        # the policy this would have reached the LLM.
        assert response.status_code == 403


@pytest.fixture
def llm_calls(monkeypatch):
    """Capture what would have been sent to a provider, without calling one."""
    calls = []

    class Message:
        content = "a reply"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    async def acompletion(**kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)

    return calls


@pytest.mark.asyncio
async def test_llm_bedrock_credentials(llm_calls, monkeypatch):
    """Bedrock gets the AWS key pair, and only when there is one to give."""
    monkeypatch.setattr(context.settings, "llm_model", "bedrock/some.model")
    monkeypatch.setattr(context.settings, "llm_api_key", "not-for-bedrock")

    prompt = Prompt(context.settings)
    result = await prompt.handle("say something", "be brief")
    assert result == "a reply"

    call = llm_calls[0]
    assert call["model"] == "bedrock/some.model"
    assert call["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "say something"},
    ]
    # Bedrock signs with a key pair, so the bearer token is not offered to it.
    assert "api_key" not in call

    monkeypatch.setattr(context.settings, "aws_key", "an-id")
    monkeypatch.setattr(context.settings, "aws_secret_key", "a-secret")
    await prompt.handle("say something")
    assert llm_calls[1]["aws_access_key_id"] == "an-id"

    # An unset key pair has to stay unset so an instance role can take over.
    monkeypatch.setattr(context.settings, "aws_key", "")
    await prompt.handle("say something")
    assert "aws_access_key_id" not in llm_calls[2]


@pytest.mark.asyncio
async def test_llm_unconfigured_model(set_redis, monkeypatch):
    """No model configured is no LLM, rather than a call that fails."""
    monkeypatch.setattr(context.settings, "llm_model", "")

    # test@gmail.com's organisation forces llm_alternatives on.
    request_in = CheckRequestIn(text="Hello world.")
    await fetch_configs_for_request(request_in, "test@gmail.com", context)
    assert request_in.config.llm_alternatives is False

    assert (
        debug_configs(CheckRequestIn(text="Hello world."), context.settings)[
            "llm_alternatives"
        ]["value"]
        is False
    )


@pytest.mark.asyncio
async def test_llm_provider_switch(llm_calls, monkeypatch):
    """Pointing at another provider is a config change and nothing else."""
    monkeypatch.setattr(context.settings, "llm_model", "openrouter/some/model")
    monkeypatch.setattr(context.settings, "llm_api_key", "a-key")
    monkeypatch.setattr(context.settings, "llm_api_base", "https://example.com/v1")

    await Prompt(context.settings).handle("say something")

    call = llm_calls[0]
    assert call["model"] == "openrouter/some/model"
    assert call["api_key"] == "a-key"
    assert call["api_base"] == "https://example.com/v1"
    # The AWS key pair is not offered to a provider that cannot use it.
    assert "aws_access_key_id" not in call
    # An omitted system prompt still gets the inclusive-language default.
    assert "inclusive language" in call["messages"][0]["content"]


@pytest.mark.asyncio
async def test_llm_model_override(llm_calls):
    """The debug routes' per-request model wins over the configured one."""
    await Prompt(context.settings).handle("hi", None, "anthropic/some-model")

    assert llm_calls[0]["model"] == "anthropic/some-model"
    assert "aws_access_key_id" not in llm_calls[0]


def test_config_options():
    """Every reported value is one a check request is allowed to send."""
    with TestClient(app) as client:
        response = client.get("/v2.0/config-options")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "public, max-age=3600"

        options = response.json()["options"]
        assert set(options) == {
            "german_gender_ending",
            "french_gender_separator",
            "gendered_roles_format",
        }

        for field, option in options.items():
            assert option["default"] in option["values"]

            for value in option["values"]:
                # The model is the same one /v2.4/check validates against, so a
                # reported value that it rejects would be a contradiction.
                assert Config(**{field: value})

            rejected = client.post(
                "/v2.4/check", json={"text": "Hello.", "config": {field: "not-a-value"}}
            )
            assert rejected.status_code == 422

        assert "*in" in options["german_gender_ending"]["values"]
        assert options["gendered_roles_format"]["default"] == "both"

        # Every value carries a label, in every locale the API serves. An
        # unlabelled one would leave an options page showing a bare `(-)`.
        for locale in LangVariantType:
            response = client.get(
                "/v2.0/config-options", params={"locale": locale.value}
            )
            assert response.status_code == 200

            for field, option in response.json()["options"].items():
                assert set(option["labels"]) == set(option["values"]), (locale, field)

        german = client.get("/v2.0/config-options", params={"locale": "de-DE"}).json()[
            "options"
        ]["german_gender_ending"]["labels"]
        assert german["(-)"] != options["german_gender_ending"]["labels"]["(-)"]


def test_api_key_mode_options_page(standalone_settings):
    """The sequence an extension in API-key mode makes from its options page.

    The options page is where a key gets entered in the first place, so the two
    lists it renders have to come back before there is a key to send.
    """
    api_key = "options-page-key"

    with TestClient(app) as client:
        context.redis.set_api_key(api_key, "options@example.com")

        # 1. Both lists, with no credential of any kind.
        categories = client.get("/v2.0/categories").json()
        assert categories["categories"]
        options = client.get("/v2.0/config-options").json()["options"]

        # 2. Signed in with the key the user just pasted in.
        auth = client.post("/v2.0/auth", json={}, headers={"x-key": api_key})
        assert auth.status_code == 200

        text = {"text": "Wir suchen einen Ninja Programmierer für unsere Kunden."}
        results = client.post(
            "/v2.4/check", json=text, headers={"x-key": api_key}
        ).json()["results"]

        # A result's `subcategory` is one of the reported keys, or the
        # `advanced_key` of one: that is what lets a toggle line up with what
        # the user sees flagged.
        keys = {}
        for category in categories["categories"]:
            keys[category["key"]] = category
            if category["advanced_key"]:
                keys[category["advanced_key"]] = category

        reported = {result["subcategory"] for result in results}
        assert reported
        assert reported <= set(keys)
        # The text is chosen to flag an advanced variant, since that is the
        # case a client gets wrong by assuming one key per toggle.
        assert any(key.endswith("_advanced") for key in reported)

        # 3. A category switched off on the options page is gone from the next
        # check, without any dashboard having said so. One toggle means both
        # keys: the base and the advanced one are matched independently.
        category = keys[sorted(reported)[0]]
        off = [key for key in (category["key"], category["advanced_key"]) if key]

        results = client.post(
            "/v2.4/check",
            json={**text, "config": {"disabled_categories": off}},
            headers={"x-key": api_key},
        ).json()["results"]
        assert not set(off) & {result["subcategory"] for result in results}

        # 4. A gender ending picked from /v2.0/config-options is honoured.
        for ending in options["german_gender_ending"]["values"]:
            response = client.post(
                "/v2.4/check",
                json={
                    "text": "Wir suchen einen Programmierer.",
                    "config": {"german_gender_ending": ending},
                },
                headers={"x-key": api_key},
            )
            assert response.status_code == 200

        context.redis.delete_api_key(api_key)
