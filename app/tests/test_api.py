from starlette.testclient import TestClient
from app.api import app


def test_docs_redirect():
    client = TestClient(app)
    response = client.get("/")
    assert response.history[0].status_code == 302
    assert response.status_code == 200
    assert response.url == "http://testserver/docs"


def test_api():
    client = TestClient(app)

    text = """Ninja are manager."""

    request_data = {
        "values": [{"text": text}]
    }

    response = client.post("/spacy_entities", json=request_data)
    assert response.status_code == 200

    first_record = response.json()["values"][0]
    assert first_record["recordId"] == "a1"
    assert first_record["errors"] == None
    assert first_record["warnings"] == None

    assert first_record["data"]["entities"] == [
        "Alexa",
        "Amazon",
        "Apple",
        "Echo and Dot",
        "Google",
        "iPhones",
        "Siri",
    ]
