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


@pytest.fixture
def client(set_redis):  # noqa: F811
    with TestClient(app) as test_client:
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


def test_the_key_gate_lets_the_sync_through_only_behind_management_auth():
    from app.settings import Settings

    assert "/api_keys" in Settings(management_auth_enabled=True).open_paths()
    assert "/api_keys" not in Settings(management_auth_enabled=False).open_paths()


def test_a_misspelt_category_is_caught_before_it_is_sent():
    with pytest.raises(ValueError, match="no such category: plain_langauge"):
        parse(
            entry(
                "a@b",
                JANE_KEY,
                "  config:\n    disabled_categories: [plain_langauge]\n",
            )
        )
