"""API keys the API mints and keeps for a client such as the dashboard.

A managed key belongs to a person (an email) and, optionally, a team. The team
decides which organisation's settings and per-team LLM limit a request with
the key gets, and the key only works while the person's synced user config
lists that team (app/auth_service.py). Keys without a team behave like the
ones `bin/api_key.py` and the key file (app/api_keys.py) mint.

Only digests are stored, so minting needs API_KEY_HMAC_KEY; rotating that
secret invalidates every managed key. The plain key is returned once, by
`mint` and `replace`. Redis holds:

- `managed_key_digest:<digest>`: the key's id;
- `managed_key:<id>`: the key's details (ManagedKey) and its digest;
- `managed_keys_email:<email>` and `managed_keys_team:<team>`: the ids, for
  listing and revoking, pruned of expired ids as they are read.

A managed key resolves only through both of the first two, never through the
`api_key:*` entries other keys use, so a key whose details are gone does not
work at all. An expiry is a Redis expiry on both, set together.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel

from app.redis import Redis

GRACE_PERIODS = (0, 86400, 604800)
MAX_KEYS_PER_EMAIL = 20


class KeyStorageUnavailable(Exception):
    """Keys cannot be minted without API_KEY_HMAC_KEY: they would be stored
    as written."""


class TooManyKeys(Exception):
    """The email already has MAX_KEYS_PER_EMAIL keys."""


class ManagedKey(BaseModel):
    id: str
    email: str
    team_id: Optional[str] = None
    name: str
    source: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    # Replaced by a newer key and working only until expires_at, the end of
    # its grace period. It cannot be replaced again: its expiry is no longer
    # the one the person chose.
    replaced: bool = False


def _details_name(key_id: str) -> str:
    return "managed_key:" + key_id


def _digest_name(digest: str) -> str:
    return "managed_key_digest:" + digest


def _email_index(email: str) -> str:
    return "managed_keys_email:" + email.lower()


def _team_index(team_id: str) -> str:
    return "managed_keys_team:" + team_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stored: str | None) -> tuple[ManagedKey, str] | None:
    """Details and digest of a stored key, or None for none or one whose
    expiry has passed but which Redis has not removed yet."""
    if stored is None:
        return None
    data = json.loads(stored)
    digest = data.pop("digest")
    details = ManagedKey.model_validate(data)
    if details.expires_at is not None and details.expires_at <= _now():
        return None
    return details, digest


def _store(db, details: ManagedKey, digest: str) -> None:
    """Write a key's entries through `db` (a pipeline), with its expiry."""
    names = [_details_name(details.id), _digest_name(digest)]
    db.set(names[0], json.dumps({**details.model_dump(mode="json"), "digest": digest}))
    db.set(names[1], details.id)
    if details.expires_at is not None:
        for name in names:
            db.expireat(name, details.expires_at)
    db.sadd(_email_index(details.email), details.id)
    if details.team_id:
        db.sadd(_team_index(details.team_id), details.id)


def _new_key(redis: Redis) -> tuple[str, str]:
    """A new key and its digest."""
    if not redis.settings.api_key_hmac_key:
        raise KeyStorageUnavailable(
            "API_KEY_HMAC_KEY must be set to mint keys: they are stored as digests"
        )
    key = secrets.token_urlsafe(32)
    return key, redis._hash_api_key(key)


def mint(
    redis: Redis,
    email: str,
    team_id: Optional[str],
    name: str,
    source: str,
    expires_at: Optional[datetime],
) -> tuple[str, ManagedKey]:
    """Mint a key. Returns the plain key, which is not stored, and its details."""
    now = _now()
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
    email = email.lower()
    if len(_ids(redis, _email_index(email))) >= MAX_KEYS_PER_EMAIL:
        raise TooManyKeys(f"An email may have at most {MAX_KEYS_PER_EMAIL} keys")

    key, digest = _new_key(redis)
    details = ManagedKey(
        id=secrets.token_hex(8),
        email=email,
        team_id=team_id or None,
        name=name,
        source=source,
        created_at=now.replace(microsecond=0),
        expires_at=expires_at,
    )
    pipe = redis.db.pipeline()
    _store(pipe, details, digest)
    pipe.execute()
    return key, details


def find(redis: Redis, key_id: str) -> ManagedKey | None:
    loaded = _parse(redis.db.get(_details_name(key_id)))
    return loaded[0] if loaded else None


def lookup(redis: Redis, api_key: str) -> ManagedKey | None:
    """The details of a presented key, or None for a key minted otherwise,
    expired or unknown."""
    digest = redis._hash_api_key(api_key)
    if not digest:
        return None
    key_id = redis.db.get(_digest_name(digest))
    if not key_id:
        return None
    loaded = _parse(redis.db.get(_details_name(key_id)))
    # The digest must match too: an id is not a secret.
    return loaded[0] if loaded and loaded[1] == digest else None


def _ids(redis: Redis, index: str) -> set[str]:
    """The ids in an index set, pruned of keys that have expired."""
    ids = set(redis.db.smembers(index))
    gone = {key_id for key_id in ids if not redis.db.exists(_details_name(key_id))}
    if gone:
        redis.db.srem(index, *gone)
    return ids - gone


def _matching(redis: Redis, email: Optional[str], team_id: Optional[str]) -> set[str]:
    if not email and not team_id:
        raise ValueError("give an email, a team or both")
    sets = []
    if email:
        sets.append(_ids(redis, _email_index(email)))
    if team_id:
        sets.append(_ids(redis, _team_index(team_id)))
    return set.intersection(*sets)


def list_keys(
    redis: Redis, email: Optional[str], team_id: Optional[str]
) -> list[ManagedKey]:
    """The keys of an email, a team, or an email in a team, oldest first."""
    keys = [find(redis, key_id) for key_id in _matching(redis, email, team_id)]
    return sorted((k for k in keys if k), key=lambda k: (k.created_at, k.id))


def _delete(pipe, key_id: str, details: ManagedKey, digest: str) -> None:
    pipe.delete(_details_name(key_id), _digest_name(digest))
    pipe.srem(_email_index(details.email), key_id)
    if details.team_id:
        pipe.srem(_team_index(details.team_id), key_id)


def revoke(redis: Redis, key_id: str) -> bool:
    """Revoke a key. False when there was none (already revoked or expired)."""
    name = _details_name(key_id)

    def remove(pipe) -> bool:
        stored = pipe.get(name)
        pipe.multi()
        if stored is None:
            return False
        data = json.loads(stored)
        digest = data.pop("digest")
        _delete(pipe, key_id, ManagedKey.model_validate(data), digest)
        return True

    return redis.db.transaction(remove, name, value_from_callable=True)


def revoke_matching(redis: Redis, email: Optional[str], team_id: Optional[str]) -> int:
    """Revoke every key of an email, a team, or an email in a team."""
    return sum(revoke(redis, key_id) for key_id in _matching(redis, email, team_id))


def replace(redis: Redis, key_id: str, grace_seconds: int) -> tuple[str, ManagedKey]:
    """A new key with the same email, team, name, source and expiry. The old
    one keeps working for `grace_seconds` (never past its own expiry), or is
    revoked at once with 0. KeyError when there is no such key, or it has
    expired, or it is revoked meanwhile."""
    if grace_seconds not in GRACE_PERIODS:
        raise ValueError(f"grace_seconds must be one of {GRACE_PERIODS}")
    key, digest = _new_key(redis)
    name = _details_name(key_id)

    def swap(pipe) -> ManagedKey:
        loaded = _parse(pipe.get(name))
        if loaded is None or loaded[0].replaced:
            raise KeyError(key_id)
        old, old_digest = loaded
        now = _now()
        details = old.model_copy(
            update={"id": secrets.token_hex(8), "created_at": now.replace(microsecond=0)}
        )
        pipe.multi()
        _store(pipe, details, digest)
        if grace_seconds == 0:
            _delete(pipe, key_id, old, old_digest)
        else:
            end = now + timedelta(seconds=grace_seconds)
            if old.expires_at is not None and old.expires_at < end:
                end = old.expires_at
            _store(pipe, old.model_copy(update={"expires_at": end, "replaced": True}), old_digest)
        return details

    details = redis.db.transaction(swap, name, value_from_callable=True)
    return key, details
