from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Use /docs to get API documentation"}

def test_read_form():
    response = client.get("/form")
    assert response.status_code == 200
 
def test_api():
    request_data = {"text": "Greenpeace is an international company with headquarters in London."}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == [{'start': 17, 'length': 13, "label": "Alter", "category": "False Positive", 'text': 'international', 'reason': 'Sie diskriminieren die Bewerber:innen aufgrund ihres Alters.', 'solution': 'Lassen Sie diesen Begriff einfach weg.'}]

def test_api_response_lang():
    request_data = {"text": "Greenpeace is an international company with headquarters in London.", "response_lang": "en_GB"}

    response = client.post("/check", json=request_data)
    assert response.status_code == 200

    first_record = response.json()
    assert first_record["language"] == "en"
    assert first_record["results"] == [{'start': 17, 'length': 13, "label": "Age", "category": "False Positive", 'text': 'international', 'reason': 'You are discriminating against applicants due to age.', 'solution': 'Simply omit this term.'}]

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
