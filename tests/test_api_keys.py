"""API keys synced from a local YAML file through `PUT /api_keys`."""

import pytest
from fastapi.testclient import TestClient

from app.api_keys import KEY_CONFIGS, SYNCED_KEYS, parse
from app.main import app
from tests.test_api import set_redis  # noqa: F401  (fixture)

JANE_KEY = "jane-secret-key-0123456789"
TOM_KEY = "tom-secret-key-0123456789"
NEW_KEY = "new-secret-key-0123456789"

JANE = {
    "email": "Jane@ACME.example",
    "key": JANE_KEY,
    "config": {"german_gender_ending": ":in"},
    "force": {"french_gender_separator": "/"},
}
TOM = {"email": "tom@example.org", "key": TOM_KEY}


def entry(email, key, extra=""):
    return f"- email: {email}\n  key: {key}\n{extra}"


def test_the_file_keeps_its_comments_out_of_the_entries():
    entries = parse(
        "# Jane Doe (ACME), HR pilot\n"
        + entry(
            "Jane@ACME.example",
            JANE_KEY,
            '  config:\n    german_gender_ending: ":in"\n',
        )
        + "\n# Tom\n"
        + entry("tom@example.org", TOM_KEY)
    )

    assert [(e.email, e.key, e.config) for e in entries] == [
        ("jane@acme.example", JANE_KEY, {"german_gender_ending": ":in"}),
        ("tom@example.org", TOM_KEY, {}),
    ]


@pytest.mark.parametrize(
    "text,message",
    [
        ("email: a@b\n", "must be a list"),
        (entry("not-an-email", JANE_KEY), "not an email"),
        (entry("a@b", "short"), "at least 20"),
        (entry("a@b", JANE_KEY, "  note: x\n"), "Extra inputs"),
        (entry("a@b", JANE_KEY, "  config:\n    gender_ending: x\n"), "no such config"),
        (
            entry("a@b", JANE_KEY, "  config:\n    german_gender_ending: star\n"),
            "german_gender_ending",
        ),
        (entry("a@b", JANE_KEY) + entry("c@d", JANE_KEY), "listed twice"),
        (
            entry("a@b", JANE_KEY)
            + entry("a@b", TOM_KEY, '  config:\n    german_gender_ending: ":in"\n'),
            "another config",
        ),
    ],
)
def test_a_broken_file_says_what_is_wrong(text, message):
    with pytest.raises(ValueError, match=message):
        parse(text)


# Every sync test runs with keys stored as written and as HMAC digests.
@pytest.fixture(params=["", "an-hmac-secret"], ids=["plain", "hmac"])
def client(request, set_redis, monkeypatch):  # noqa: F811
    with TestClient(app) as test_client:
        monkeypatch.setattr(
            app.state.context.settings, "api_key_hmac_key", request.param
        )
        db = app.state.context.redis.db
        db.delete(SYNCED_KEYS, KEY_CONFIGS)
        yield test_client
        for name in db.smembers(SYNCED_KEYS):
            db.delete(name)
        db.delete(SYNCED_KEYS, KEY_CONFIGS)


def sync(client, *entries, dry_run=False):
    return client.put(
        "/api_keys", params={"dry_run": dry_run}, json={"entries": list(entries)}
    )


def check(client, key, text, lang="de", config=None):
    return client.post(
        "/v2.4/check",
        json={"text": text, "lang": lang, "config": config or {}},
        headers={"x-key": key},
    )


def auth(client, key):
    return client.post("/v2.0/auth", headers={"x-key": key})


def test_a_dry_run_changes_nothing(client):
    response = sync(client, JANE, TOM, dry_run=True)

    assert response.json()["added"] == ["jane@acme.example", "tom@example.org"]
    assert auth(client, JANE_KEY).status_code == 403


def test_a_sync_adds_and_revokes_keys(client):
    first = sync(client, JANE, TOM).json()
    assert first["added"] == ["jane@acme.example", "tom@example.org"]
    assert first["configs"] == ["jane@acme.example"]
    assert auth(client, JANE_KEY).status_code == 200
    assert auth(client, TOM_KEY).status_code == 200

    # Tom's entry removed, a new key for Jane added.
    second = sync(client, JANE, {**JANE, "key": NEW_KEY}).json()
    assert second["revoked"] == ["tom@example.org"]
    assert second["added"] == ["jane@acme.example"]
    assert second["unchanged"] == ["jane@acme.example"]
    assert auth(client, TOM_KEY).status_code == 403
    assert auth(client, NEW_KEY).status_code == 200

    # The response names emails, never keys.
    assert JANE_KEY not in str(first) + str(second)


def test_keys_minted_otherwise_are_left_alone(client):
    app.state.context.redis.set_api_key("dashboard-key-0123456789", "dash@example.org")
    sync(client, JANE)
    sync(client, TOM)

    assert app.state.context.redis.get_api_key_email("dashboard-key-0123456789") == (
        "dash@example.org"
    )

    # Nor taken over for another email: the whole sync is refused.
    response = sync(client, {**TOM, "key": "dashboard-key-0123456789"})
    assert response.status_code == 409
    assert "tom@example.org" in response.json()["detail"]
    assert app.state.context.redis.get_api_key_email(TOM_KEY) == "tom@example.org"


def test_auth_reports_the_keys_config(client):
    sync(client, JANE)
    config = auth(client, JANE_KEY).json()["config"]

    assert config["german_gender_ending"] == {"value": ":in", "status": "suggestion"}
    assert config["french_gender_separator"] == {"value": "/", "status": "force"}


def test_a_keys_config_is_the_default_and_its_force_wins(client):
    sync(client, JANE, TOM)
    text = "Die Lehrer*innen kommen."

    # The key's default applies where the request says nothing ...
    assert check(client, JANE_KEY, text).json()["gender_separator"] == ":in"
    # ... and the request's own choice where it does.
    chosen = check(client, JANE_KEY, text, config={"german_gender_ending": "/in"})
    assert chosen.json()["gender_separator"] == "/in"

    # A force applies whatever the request asks for.
    forced = check(
        client,
        JANE_KEY,
        "Les enseignant·es arrivent.",
        "fr",
        {"french_gender_separator": "·"},
    )
    assert forced.json()["gender_separator"] == "/"

    # Without a config of its own, the deployment's defaults.
    assert check(client, TOM_KEY, text).json()["gender_separator"] == "*in"


def test_a_sync_is_checked_like_the_file(client):
    response = sync(client, JANE, {**TOM, "key": JANE_KEY})

    assert response.status_code == 422
    assert "listed twice" in response.json()["detail"]


def test_a_misspelt_category_is_caught_before_it_is_sent():
    with pytest.raises(ValueError, match="no such category: plain_langauge"):
        parse(
            entry(
                "a@b",
                JANE_KEY,
                "  config:\n    disabled_categories: [plain_langauge]\n",
            )
        )


def test_a_deployment_limit_is_not_a_key_setting():
    with pytest.raises(ValueError, match="cannot set alternatives_max_count"):
        parse(entry("a@b", JANE_KEY, "  config:\n    alternatives_max_count: 50\n"))


def test_the_sync_says_what_will_not_take_effect(client, monkeypatch):
    from app.models import LlmAccessType

    monkeypatch.setattr(
        app.state.context.settings, "llm_access", LlmAccessType.DISABLED
    )
    redis = app.state.context.redis
    redis.db.set(redis.get_user_id("jane@acme.example"), "{}")
    try:
        with_llm = {**TOM, "config": {"llm_alternatives": True}}
        warnings = sync(client, JANE, with_llm, dry_run=True).json()["warnings"]
    finally:
        redis.db.delete(redis.get_user_id("jane@acme.example"))

    hmac_note = "API_KEY_HMAC_KEY is not set: the keys are stored in Redis as written"
    assert [w for w in warnings if w != hmac_note] == [
        "jane@acme.example: config ignored, a config synced from the dashboard "
        "for this email wins",
        "tom@example.org: llm_alternatives has no effect, LLM_ACCESS "
        "(or LLM_ALLOWED_USERS) does not allow it",
    ]


def test_an_empty_file_revokes_nothing_unless_asked(client):
    sync(client, JANE)

    refused = client.put("/api_keys", json={"entries": []})
    assert refused.status_code == 422
    assert "revoke every synced key" in refused.json()["detail"]
    assert auth(client, JANE_KEY).status_code == 200

    emptied = client.put(
        "/api_keys", params={"allow_empty": True}, json={"entries": []}
    )
    assert emptied.json()["revoked"] == ["jane@acme.example"]
    assert auth(client, JANE_KEY).status_code == 403


def test_a_key_minted_elsewhere_for_the_same_email_stays_unmanaged(client):
    """Listing a dashboard key in the file does not take it over, so deleting
    it from the file later cannot revoke it either."""
    redis = app.state.context.redis
    redis.set_api_key("dashboard-key-0123456789", "tom@example.org")

    first = sync(client, {**TOM, "key": "dashboard-key-0123456789"}, JANE).json()
    assert first["unmanaged"] == ["tom@example.org"]
    assert first["added"] == ["jane@acme.example"]

    sync(client, JANE)
    assert redis.get_api_key_email("dashboard-key-0123456789") == "tom@example.org"


def test_a_key_moving_to_another_email_is_reported(client):
    sync(client, JANE)
    moved = sync(client, {**TOM, "key": JANE_KEY}).json()

    assert moved["moved"] == ["jane@acme.example -> tom@example.org"]
    assert app.state.context.redis.get_api_key_email(JANE_KEY) == "tom@example.org"


def test_a_stored_config_that_no_longer_validates_does_not_fail_requests(client):
    """After a deploy that renamed an option or narrowed a value, the key's
    user keeps working; what no longer applies is left out."""
    sync(client, JANE)
    app.state.context.redis.db.hset(
        KEY_CONFIGS,
        "jane@acme.example",
        '{"config": {"renamed_option": 1, "german_gender_ending": "bogus"},'
        ' "force": {}}',
    )

    assert auth(client, JANE_KEY).status_code == 200
    assert check(client, JANE_KEY, "Die Lehrer*innen kommen.").status_code == 200


def test_errors_never_quote_a_key(client):
    typo = {"email": "a@b", "kye": JANE_KEY}
    response = client.put("/api_keys", json={"entries": [typo]})

    assert response.status_code == 422
    assert JANE_KEY not in response.text

    with pytest.raises(ValueError) as raised:
        parse(f"- email: a@b\n  kye: {JANE_KEY}\n")
    assert JANE_KEY not in str(raised.value)

    with pytest.raises(ValueError, match=r"not valid YAML at line \d") as raised:
        parse(f"- email: a@b\n  key: [{JANE_KEY}\n")
    assert JANE_KEY not in str(raised.value)


def test_minting_writes_a_private_file_that_stays_valid(tmp_path):
    import argparse
    import importlib.util
    import os
    import stat

    spec = importlib.util.spec_from_file_location("api_key_cli", "bin/api_key.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    path = tmp_path / "api_keys.yaml"
    args = argparse.Namespace(
        file=str(path), email="[odd]@example.org", api_key=None, note="An odd one"
    )
    assert cli.create_in_file(args) == 0

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    entries = parse(path.read_text())
    assert [entry.email for entry in entries] == ["[odd]@example.org"]
    assert path.read_text().startswith("# An odd one\n")
