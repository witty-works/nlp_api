import json
import os

import pytest
from pathlib import Path

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


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_cases").iterdir()),
)
def test_json(case_dir, snapshot):

    # Read input files from the case directory.
    input_json = case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_orthography").iterdir()),
)
def test_orthoraphy(case_dir, snapshot):

    # Read input files from the case directory.
    input_json = case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_gender_ending").iterdir()),
)
def test_gender_ending(case_dir, snapshot):

    # Read input files from the case directory.
    input_json = case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = case_dir
    snapshot.assert_match(output, "output.json")


def test_api_missing_data():
    response = client.post("/check")
    assert response.status_code == 422


def test_api_empty_data():
    request_data = {}

    response = client.post("/check", json=request_data)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_gender_ending").iterdir()),
)
def test_gender_ending(case_dir, snapshot):

    # Read input files from the case directory.
    input_json = case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_language_detection").iterdir()),
)
def test_language_detection(case_dir, snapshot):

    # Read input files from the case directory.
    input_json = case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 200
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    # Snapshot the return value.
    snapshot.snapshot_dir = case_dir
    snapshot.assert_match(output, "output.json")


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_language_detection_fail").iterdir()),
)
def test_language_detection_fail(case_dir, snapshot):

    # Read input files from the case directory.
    input_json = case_dir.joinpath("input.json").read_text()
    # Call the tested endpoint.
    response = client.post("/check", json=json.loads(input_json))
    assert response.status_code == 422


def test_log(snapshot):
    # Read input files from the case directory.
    case_dir = Path("tests/test_log")
    input_json = case_dir.joinpath("input.json").read_text()
    print("input_json", input_json)
    # Call the tested endpoint.
    response = client.post("/log", json=json.loads(input_json))
    assert response.status_code == 201
    # output must be string
    output = json.dumps(response.json(), sort_keys=True, indent=4, ensure_ascii=False)
    snapshot.snapshot_dir = "tests/test_log"
    snapshot.assert_match(output, "output.json")
