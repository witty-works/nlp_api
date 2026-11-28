"""Keys minted through the API for a person and, optionally, a team
(app/managed_keys.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from fakeredis import FakeStrictRedis

from app import managed_keys
from app.managed_keys import KeyStorageUnavailable, TooManyKeys
from app.redis import Redis
from app.settings import Settings


@pytest.fixture
def redis():
    settings = Settings().model_copy(update={"api_key_hmac_key": "a-secret"})
    return Redis(settings, FakeStrictRedis(decode_responses=True))


def everything(redis):
    """Every name and value Redis holds, as one string."""
    parts = []
    for name in redis.db.scan_iter("*"):
        parts.append(name)
        kind = redis.db.type(name)
        if kind == "string":
            parts.append(redis.db.get(name))
        elif kind == "set":
            parts.extend(redis.db.smembers(name))
    return " ".join(parts)


def later(**delta):
    return datetime.now(timezone.utc) + timedelta(**delta)


def test_mint_stores_only_a_digest(redis):
    key, details = managed_keys.mint(
        redis, "Jane@ACME.example", "team-a", "Editor", "dashboard", None
    )

    assert len(key) >= 40
    assert key not in everything(redis)
    # Resolved only through its details, so a key without them fails closed.
    assert redis.get_api_key_email(key) is None
    assert details.email == "jane@acme.example"
    assert details.team_id == "team-a"
    assert details.name == "Editor"
    assert details.source == "dashboard"
    assert details.expires_at is None
    assert managed_keys.lookup(redis, key) == details


def test_mint_refused_without_hmac_secret():
    plain = Redis(Settings().model_copy(update={"api_key_hmac_key": ""}), FakeStrictRedis(decode_responses=True))

    with pytest.raises(KeyStorageUnavailable):
        managed_keys.mint(plain, "jane@acme.example", None, "Editor", "api", None)


def test_list_by_email_team_and_both(redis):
    managed_keys.mint(redis, "jane@acme.example", "team-a", "A", "api", None)
    managed_keys.mint(redis, "jane@acme.example", "team-b", "B", "api", None)
    managed_keys.mint(redis, "tom@acme.example", "team-a", "T", "api", None)

    def names(**filters):
        return sorted(k.name for k in managed_keys.list_keys(redis, **filters))

    assert names(email="Jane@acme.example", team_id=None) == ["A", "B"]
    assert names(email=None, team_id="team-a") == ["A", "T"]
    assert names(email="jane@acme.example", team_id="team-a") == ["A"]
    with pytest.raises(ValueError):
        managed_keys.list_keys(redis, email=None, team_id=None)


def test_expired_key_neither_resolves_nor_lists(redis):
    key, details = managed_keys.mint(
        redis, "jane@acme.example", "team-a", "Pilot", "api", later(days=30)
    )
    expiring = [name for name in redis.db.scan_iter("*") if redis.db.ttl(name) > 0]
    assert len(expiring) == 2

    # What Redis does once the expiry passes; the index sets still hold the id.
    redis.db.delete(*expiring)

    assert managed_keys.lookup(redis, key) is None
    assert managed_keys.list_keys(redis, email="jane@acme.example", team_id=None) == []
    assert managed_keys.find(redis, details.id) is None


def test_expiry_in_the_past_is_refused(redis):
    with pytest.raises(ValueError):
        managed_keys.mint(redis, "jane@acme.example", None, "Old", "api", later(seconds=-1))


def test_revoke_matching_by_team_leaves_other_teams(redis):
    a, _ = managed_keys.mint(redis, "jane@acme.example", "team-a", "A", "api", None)
    b, _ = managed_keys.mint(redis, "jane@acme.example", "team-b", "B", "api", None)

    assert managed_keys.revoke_matching(redis, email="jane@acme.example", team_id="team-a") == 1
    assert managed_keys.lookup(redis, a) is None
    assert managed_keys.lookup(redis, b).team_id == "team-b"
    assert managed_keys.revoke_matching(redis, email="jane@acme.example", team_id="team-a") == 0


def test_revoke_is_idempotent(redis):
    key, details = managed_keys.mint(redis, "jane@acme.example", None, "A", "api", None)

    assert managed_keys.revoke(redis, details.id) is True
    assert managed_keys.revoke(redis, details.id) is False
    assert managed_keys.lookup(redis, key) is None
    assert everything(redis) == ""


def test_replace_with_grace_keeps_old_key_until_then(redis):
    old, details = managed_keys.mint(redis, "jane@acme.example", "team-a", "Editor", "dashboard", None)

    new, replacement = managed_keys.replace(redis, details.id, 86400)

    assert new != old
    still = managed_keys.lookup(redis, old)
    assert still is not None
    assert 0 < redis.db.ttl("managed_key:" + details.id) <= 86400
    # The page shows when the old key stops working.
    assert still.expires_at is not None
    assert still.expires_at <= later(seconds=86401)
    assert (replacement.name, replacement.team_id, replacement.source) == ("Editor", "team-a", "dashboard")
    assert replacement.expires_at is None
    assert managed_keys.lookup(redis, new) == replacement


def test_replace_without_grace_revokes_at_once(redis):
    old, details = managed_keys.mint(redis, "jane@acme.example", None, "Editor", "api", None)

    managed_keys.replace(redis, details.id, 0)

    assert managed_keys.lookup(redis, old) is None
    assert managed_keys.find(redis, details.id) is None


def test_replace_never_extends_expiry(redis):
    expires = later(hours=1)
    old, details = managed_keys.mint(redis, "jane@acme.example", None, "Pilot", "api", expires)

    _, replacement = managed_keys.replace(redis, details.id, 604800)

    assert redis.db.ttl("managed_key:" + details.id) <= 3600
    assert managed_keys.lookup(redis, old).expires_at == details.expires_at
    assert replacement.expires_at == details.expires_at


def test_replace_missing_key(redis):
    with pytest.raises(KeyError):
        managed_keys.replace(redis, "nope", 0)


def test_replace_refuses_a_key_past_its_expiry(redis):
    _, details = managed_keys.mint(redis, "jane@acme.example", None, "Pilot", "api", later(hours=1))
    # Expired by the clock, not yet removed by Redis.
    stored = redis.db.get("managed_key:" + details.id)
    redis.db.set(
        "managed_key:" + details.id,
        stored.replace(details.expires_at.isoformat().replace("+00:00", "Z"), "2000-01-01T00:00:00Z"),
    )

    with pytest.raises(KeyError):
        managed_keys.replace(redis, details.id, 0)


def test_at_most_twenty_keys_per_person(redis):
    for number in range(20):
        managed_keys.mint(redis, "jane@acme.example", None, f"K{number}", "api", None)

    with pytest.raises(TooManyKeys):
        managed_keys.mint(redis, "Jane@acme.example", None, "One more", "api", None)
    managed_keys.mint(redis, "tom@acme.example", None, "Tom", "api", None)


def test_the_limit_holds_when_another_key_is_minted_meanwhile(redis, monkeypatch):
    """Two requests for the 20th key at once: the one that counted before the
    other wrote must not get a 21st."""
    email = "jane@acme.example"
    for number in range(19):
        managed_keys.mint(redis, email, None, f"K{number}", "api", None)

    original = managed_keys._store
    raced = []

    def another_request_meanwhile(db, details, digest):
        # As this request writes its key, after it counted, the other mints.
        if not raced:
            raced.append(True)
            managed_keys.mint(redis, email, None, "Meanwhile", "api", None)
        return original(db, details, digest)

    monkeypatch.setattr(managed_keys, "_store", another_request_meanwhile)

    with pytest.raises(TooManyKeys):
        managed_keys.mint(redis, email, None, "One too many", "api", None)
    assert len(managed_keys._ids(redis, managed_keys._email_index(email))) == 20


def test_a_key_in_its_grace_period_cannot_be_replaced_again(redis):
    _, details = managed_keys.mint(redis, "jane@acme.example", None, "Editor", "api", None)
    managed_keys.replace(redis, details.id, 604800)

    with pytest.raises(KeyError):
        managed_keys.replace(redis, details.id, 604800)


def test_revoke_matching_catches_a_key_replaced_meanwhile(redis, monkeypatch):
    _, details = managed_keys.mint(redis, "jane@acme.example", "team-a", "Editor", "api", None)
    revoke = managed_keys.revoke
    replaced = []

    def replace_first(redis, key_id):
        # The dashboard replaces the key while the person is being removed.
        if not replaced:
            replaced.append(managed_keys.replace(redis, key_id, 604800))
        return revoke(redis, key_id)

    monkeypatch.setattr(managed_keys, "revoke", replace_first)

    managed_keys.revoke_matching(redis, email=None, team_id="team-a")

    assert replaced
    assert managed_keys.list_keys(redis, email="jane@acme.example", team_id=None) == []


def test_a_key_in_its_grace_period_counts_towards_the_limit(redis):
    ids = [managed_keys.mint(redis, "jane@acme.example", None, f"K{n}", "api", None)[1].id for n in range(20)]

    # Replacing is never refused for the limit, but the old key counts until
    # its grace period ends, so at most 20 keys are minted beyond that.
    managed_keys.replace(redis, ids[0], 86400)
    with pytest.raises(TooManyKeys):
        managed_keys.mint(redis, "jane@acme.example", None, "One more", "api", None)
