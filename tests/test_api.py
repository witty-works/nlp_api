import json
import os

import pytest
import yaml
from pathlib import Path

from fastapi.applications import FastAPI
from fastapi.testclient import TestClient
from app.main import app
from app.main import redis, set_rules
import json
from app.models import RequestIn

client = TestClient(app)


def json_to_yaml(json_string):
    obj = json.loads(json_string)
    return yaml.dump(obj, indent=2)


@pytest.mark.parametrize(
    "case_dir",
    list(Path("tests/test_cases").iterdir()),
)
def test_json(case_dir, snapshot):
    # Read input files from the case directory.
    print("LALALALAL")
    input_json = case_dir.joinpath("input.json").read_text()
    print("**********")
    print(input_json)
    print("*********")
    # Call the tested function.
    response = client.post("/check", json=input_json)
    output = response.json
    print(type(str(output)))
    output_yaml = json_to_yaml(input_json)
    print(type(output_yaml))
    # Snapshot the return value.

    snapshot.snapshot_dir = case_dir
    snapshot.assert_match(output_yaml, "output.yaml")
