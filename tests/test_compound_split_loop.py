"""A German noun the compound splitter cannot split ends its lookup.

german_nouns' parse_compound returns such a word unsplit ("Vielfaches" ->
["Vielfaches"]). The lookup used to retry the same word for as long as no
declension was found, which never ended and held the event loop, so one
word in one request stopped the API answering anyone.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, context
from tests.test_api import set_redis  # noqa: F401  (fixture)

# Far more splits than any word needs. The test counts them instead of timing
# the request out: the test client runs the app in another thread, which an
# alarm does not reach.
MAX_SPLITS = 200


class Hung(Exception):
    pass


@pytest.mark.parametrize(
    "text",
    [
        "Der Wert muss ein Vielfaches von 5 sein.",
        "Ein Vielfaches davon.",
    ],
)
def test_a_noun_the_splitter_returns_unsplit_is_checked(text, set_redis, monkeypatch):  # noqa: F811
    with TestClient(app) as client:
        splitter = context.nouns.nouns
        split = splitter.parse_compound
        calls = 0

        def counted(word):
            nonlocal calls
            calls += 1
            if calls > MAX_SPLITS:
                raise Hung(f"the noun lookup split {calls} times")
            return split(word)

        monkeypatch.setattr(splitter, "parse_compound", counted)
        response = client.post(
            "/v2.4/check",
            json={"text": text, "lang": "de"},
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )

    assert response.status_code == 200
    assert response.json()["language"] == "de"
