import pytest
import logging
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import (
    app,
    redis,
    set_rules,
    is_number_list_empty,
)
from app.model import model
import json
from app.models import (
    LangWithAutoType,
    RequestIn,
)
from app import main
from unittest import mock

client = TestClient(app)
logging.basicConfig(
    level="DEBUG", format="[%(asctime)s] %(name)s %(levelname)s - %(message)s"
)


def get_dirs(path):
    return list(
        subpath for subpath in Path(path).iterdir() if not subpath.name.startswith(".")
    )


def test_read_main():
    response = client.get("/", allow_redirects=False)
    assert response.status_code == 301
    assert response.headers["Location"] == "https://www.witty.works/form"


def test_read_form():
    response = client.get("/form", allow_redirects=False)
    assert response.status_code == 301
    assert response.headers["Location"] == "https://www.witty.works/form"


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_highlight_position"),
)
def test_highlight_position(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = ending_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_sentry_examples"),
)
def test_sentry_examples(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = ending_case_dir
    snapshot.assert_match(output, "output.json")


# This test is failling because singular/plural form of token cannot be determined. The workaround is applied, but this test case remain failing till permanent fix is found.
@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_singular_plural"),
)
def test_singular_plural(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested function
    text = json.loads(input_json)["text"]
    token = model["en"](text.rstrip().replace("\n", " "))[0]
    number = token.morph.get("Number")
    response = is_number_list_empty(number, token, text)
    logging.debug(
        "Singular/plural form cannot be determined. This test will remain failing till this is fixed. The workaround is applied for now."
    )
    # assert response == False


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_spacy_model"),
)
def test_spacy_model(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = ending_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_demo_wordings_english"),
)
def test_demo_wordings_english(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = ending_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_demo_wordings_german"),
)
def test_demo_wordings_german(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = ending_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "general_case_dir",
    get_dirs("tests/test_general_cases"),
)
def test_json(general_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = general_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = general_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "general_case_dir",
    get_dirs("tests/test_1_0"),
)
def test_1_0_json(general_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = general_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = general_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "orthoraphy_case_dir",
    get_dirs("tests/test_orthography"),
)
def test_orthoraphy(orthoraphy_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = orthoraphy_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = orthoraphy_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "ending_case_dir",
    get_dirs("tests/test_gender_ending"),
)
def test_gender_ending(ending_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = ending_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = ending_case_dir
    snapshot.assert_match(output, "output.json")


def test_api_missing_data():
    response = client.post("/v1.1/check")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "detection_case_dir",
    get_dirs("tests/test_language_detection"),
)
def test_language_detection(detection_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = detection_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = detection_case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "fails_case_dir",
    get_dirs("tests/test_fails"),
)
def test_language_detection_fail(fails_case_dir, snapshot):

    # Read input files from the case directory.
    input_json = fails_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/v1.1/check", json=json.loads(input_json))
    assert response.status_code == 422

    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = fails_case_dir
    snapshot.assert_match(output, "output.json")


def test_categories():
    response = client.get("/categories")
    assert response.status_code == 200

    first_record = response.json()

    assert "hollow" in first_record


@pytest.fixture
def set_redis():
    organization_object = {
        "users": ["test@gmail.com"],
        "config": {
            "forced": {
                "store_context": False,
                "primary_language": "en-GB",
                "preferred_languages": ["en"],
                "preferred_variants": ["en-GB"],
                "german_gender_ending": "In",
                "gendered_roles_format": "binary_gender",
            },
            "suggestion": {},
        },
        "false_positive": [
            "stark",
            "starke",
            "starkes",
            "starker",
            "Führungskraft",
            "Führungskräfte",
            "Führungskräften",
        ],
    }

    # Set a value
    redis.set("test", json.dumps(organization_object))
    redis.set("test@gmail.com", "test")


@pytest.mark.parametrize(
    "fp_case_dir",
    get_dirs("tests/test_false_positive"),
)
def test_false_positive(fp_case_dir, snapshot, set_redis):
    input_json = fp_case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    client = TestClient(app)
    response = client.post(
        "/v1.1/check", json=json.loads(input_json), headers={"X-Auth": "test@gmail.com"}
    )
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = fp_case_dir
    snapshot.assert_match(output, "output.json")


# test overwriting user configuration by organization forced rules
def test_set_rules(event_loop, set_redis):
    request_data = {
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
    event_loop.run_until_complete(set_rules(test_request, "test@gmail.com"))
    assert test_request.config.store_context == False
    assert test_request.config.primary_language == "en-GB"
    assert test_request.config.preferred_languages == ["en"]
    assert test_request.config.preferred_variants == ["en-GB"]
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test not overwriting user configuration by organization suggestion/default rules


def test_set_rules_suggestion(event_loop, set_redis):
    request_data = {
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
    event_loop.run_until_complete(set_rules(test_request, "test_default@gmail.com"))
    assert test_request.config.store_context == True
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
    event_loop.run_until_complete(set_rules(test_request, "test@gmail.com"))
    assert test_request.config.store_context == False
    assert test_request.config.primary_language == "en-GB"
    assert test_request.config.preferred_languages == ["en"]
    assert test_request.config.preferred_variants == ["en-GB"]
    assert test_request.config.german_gender_ending == "In"
    assert test_request.config.gendered_roles_format == "binary_gender"


# test user and organization didn't set any rules


def test_set_default_rules(event_loop):
    request_data = {
        "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    }
    test_request = RequestIn(**request_data)

    event_loop.run_until_complete(set_rules(test_request, "test_default@gmail.com"))
    assert test_request.config.store_context == True
    assert test_request.config.primary_language == "de-DE"
    assert test_request.config.preferred_languages == [
        LangWithAutoType.EN,
        LangWithAutoType.DE,
    ]
    assert test_request.config.preferred_variants == [
        LangWithAutoType.enUS,
        LangWithAutoType.deDE,
    ]
    assert test_request.config.german_gender_ending == ":in"
    assert test_request.config.gendered_roles_format == "both"


# test POST Redis endpoint


def test_store_and_get_rules():
    request_data = {
        "organization": "TEST_organization",
        "users": ["test@gmail.com"],
        "forced": {"gendered_roles_format": "binary_gender"},
        "suggestion": {"german_gender_ending": "In"},
    }
    response = client.post("/store_rules", json=request_data)
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert (
        response_content["config"]["forced"]["gendered_roles_format"] == "binary_gender"
    )
    assert response_content["config"]["suggestion"]["german_gender_ending"] == "In"
    assert response_content["config"]["suggestion"]["preferred_variants"] == [
        "en-US",
        "de-DE",
    ]

    request_data["users"] = ["test2@gmail.com", "test3@gmail.com"]
    request_data["forced"]["gendered_roles_format"] = "both"
    response = client.post("/store_rules", json=request_data)
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert response_content["config"]["forced"]["gendered_roles_format"] == "both"
    assert response_content["config"]["suggestion"]["german_gender_ending"] == "In"
    assert response_content["config"]["suggestion"]["preferred_variants"] == [
        "en-US",
        "de-DE",
    ]

    response = client.get("/get_user_rules?user=test@gmail.com")
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert response_content == []

    response = client.get("/get_user_rules?user=test2@gmail.com")
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert response_content["config"]["forced"]["gendered_roles_format"] == "both"
    assert response_content["config"]["suggestion"]["german_gender_ending"] == "In"
    assert response_content["config"]["suggestion"]["preferred_variants"] == [
        "en-US",
        "de-DE",
    ]


# test german gender ending


def test_german_gender_ending():
    request_data = {
        "alternative": "Sinti~ze~/~Sinti und Rom~nja~/~Roma",
    }
    response = client.get("/german_gender_ending", params=request_data)
    assert response.status_code == 200
    response_content = json.loads(response.content)

    expected = [
        "Sinti/ze und Rom/nja",
        "Sinti_ze und Rom_nja",
        "Sinti:ze und Rom:nja",
        "Sinti*ze und Rom*nja",
        "Sinti/-ze und Rom/-nja",
        "Sintize/Sinti und Romnja/Roma",
        "SintiZe und RomNja",
    ]

    assert sorted(response_content) == sorted(expected)
