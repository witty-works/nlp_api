"""The check's token loop moves forward whatever a check returns.

Each check returns the index of the next token to look at. One that returns
an earlier index is logged as an error (check_continue), and the loop then
went on from that index, so it read the same token again, got the same
answer, and never ended: one request held the event loop for good.
"""

from fastapi.testclient import TestClient

from app.main import app, context
from tests.test_api import set_redis  # noqa: F401  (fixture)

# Far more calls than a six-token sentence needs; a loop that goes back
# exceeds it at once. The test cannot time the request out instead: the
# test client runs the app in another thread, which an alarm does not reach.
MAX_CALLS = 200


class Hung(Exception):
    pass


def test_a_check_that_returns_an_earlier_token_does_not_stop_the_loop(
    set_redis, monkeypatch  # noqa: F811
):
    calls = 0

    async def backwards(config, client, language, text, token_index, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > MAX_CALLS:
            raise Hung(f"the token loop called the rule check {calls} times")
        return max(token_index - 1, 0)

    with TestClient(app, raise_server_exceptions=True) as client:
        monkeypatch.setattr(context.rule_check, "handle", backwards)
        response = client.post(
            "/v2.4/check",
            json={"text": "The chairman called the policeman.", "lang": "en"},
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )

    assert response.status_code == 200
    assert calls <= MAX_CALLS
