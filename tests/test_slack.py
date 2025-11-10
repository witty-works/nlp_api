import time
import hmac
import hashlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def slack_signature(secret: str, body: str, ts: str | None = None) -> tuple[str, str]:
    ts = ts or str(int(time.time()))
    base = f"v0:{ts}:{body}".encode()
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return sig, ts


def test_register_routes_without_slack(monkeypatch):
    # Import locally to allow monkey-patching settings getter
    import app.routes as routes_pkg

    class FakeSettings:
        slack_enabled = False

    monkeypatch.setattr(routes_pkg, "get_settings", lambda: FakeSettings())

    app = FastAPI()
    routes_pkg.register_routes(app)

    client = TestClient(app)
    # Slack commands endpoint should not be present
    r = client.post("/slack/commands")
    assert r.status_code in (404, 405)


def test_register_routes_with_slack_but_not_initialized(monkeypatch):
    # Import locally to allow monkey-patching settings getter
    import app.routes as routes_pkg

    class FakeSettings:
        slack_enabled = True

    monkeypatch.setattr(routes_pkg, "get_settings", lambda: FakeSettings())

    app = FastAPI()
    routes_pkg.register_routes(app)

    client = TestClient(app)
    # Router is included, but Bolt handler is not initialized -> 503
    r = client.post("/slack/commands")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_process_command_witty_blocks_smoke(monkeypatch):
    from app.bolt import process_command_witty
    from app.models import Language, ResultOut, ResultExplanation

    # Minimal objects to simulate one result
    language = Language(locale="en-US", translations={})
    result = ResultOut(
        text="term",
        text_id="term",
        category="general",
        subcategory="hidden_image",
        start=0,
        end=4,
        alternatives=[],
        label="Label",
        explanation=ResultExplanation(text="Explain", url=None, icon=None),
        proficiency_level="basic",
    )

    class DummyRespond:
        def __init__(self):
            self.calls = []

        async def __call__(self, *, blocks):  # Slack SDK passes named arg
            self.calls.append(blocks)

    respond = DummyRespond()

    await process_command_witty(
        text="Hello",
        language=language,
        limit_reached=False,
        results=[result],
        respond=respond,
    )

    assert len(respond.calls) == 1
    # Basic sanity: at least two sections (header + details)
    assert len(respond.calls[0]) >= 2
