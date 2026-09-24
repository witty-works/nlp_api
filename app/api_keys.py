"""API keys kept in a local YAML file and synced to the API.

The file lives with whoever hands out the keys, never on the server or in the
repository (it holds the keys themselves):

    # Jane Doe (ACME), HR pilot until 2026-12
    - email: jane@acme.example
      key: 3kP9vYx0…               # `bin/api_key.py create --file` mints one
      config:                      # optional: used where a request does not say
        german_gender_ending: ":in"
      force:                       # optional: used whatever a request says
        french_gender_separator: "·"

`bin/sync_api_keys.py` sends it to `PUT /api_keys`, which makes the server
match it: new keys are added, keys it synced before and that are no longer
listed are revoked, and each email's `config` and `force` are replaced. Keys
minted any other way (the dashboard, `bin/api_key.py` without `--file`,
DEFAULT_API_KEY) are left alone.

A key resolves to its entry's email, which is what the rest of the API knows a
user by: the email's config, the pseudonymous id in the metrics. Several keys
may share an email (while rotating one, say), as long as their `config` and
`force` agree. A config synced from the dashboard for the same email wins.
"""

import json
import re
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from app.categories import get_category_keys
from app.models import Config

# Redis: the `api_key:*` entries the last sync wrote, so the next one can
# revoke those it no longer lists, and each email's config.
SYNCED_KEYS = "api_keys_synced"
KEY_CONFIGS = "api_key_configs"


# Config fields a key may not set: the deployment's limits, not a user's
# preferences.
NOT_PER_KEY = {"alternatives_max_count": "the deployment's ALTERNATIVES_MAX_COUNT"}


def _checked_config(fields: dict[str, Any], name: str) -> dict[str, Any]:
    unknown = sorted(set(fields) - set(Config.model_fields))
    if unknown:
        raise ValueError(f"{name} has no such config option: {', '.join(unknown)}")
    blocked = sorted(set(fields) & set(NOT_PER_KEY))
    if blocked:
        field = blocked[0]
        raise ValueError(f"{name} cannot set {field}: it is {NOT_PER_KEY[field]}")
    # Validated as a request's config would be, so a typo in a value fails
    # before it is sent rather than on the first request that uses it. A
    # request's config takes any category name, where a typo would silently
    # disable nothing, so those are checked here too.
    Config(**fields)
    unknown = sorted(
        set(fields.get("disabled_categories") or []) - set(get_category_keys())
    )
    if unknown:
        raise ValueError(f"{name} has no such category: {', '.join(unknown)}")

    return fields


class KeyConfig(BaseModel):
    config: dict[str, Any] = {}
    force: dict[str, Any] = {}

    @field_validator("config")
    @classmethod
    def valid_config(cls, config: dict) -> dict:
        return _checked_config(config or {}, "config")

    @field_validator("force")
    @classmethod
    def valid_force(cls, force: dict) -> dict:
        return _checked_config(force or {}, "force")


class ApiKeyEntry(KeyConfig):
    model_config = ConfigDict(extra="forbid")

    email: str
    key: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, email: str) -> str:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
            raise ValueError(f"not an email: {email!r}")

        return email.lower()

    @field_validator("key")
    @classmethod
    def valid_key(cls, key: str) -> str:
        # What `bin/api_key.py` mints is 43 characters; anything much shorter
        # is guessable.
        if len(key) < 20 or not re.fullmatch(r"[A-Za-z0-9_\-]+", key):
            raise ValueError("a key needs at least 20 letters, digits, - or _")

        return key


def check_entries(entries: list[ApiKeyEntry]) -> None:
    """Raises ValueError for a key listed twice or an email with two configs."""
    keys: set[str] = set()
    configs: dict[str, KeyConfig] = {}
    for position, entry in enumerate(entries, start=1):
        if entry.key in keys:
            raise ValueError(f"entry {position}: the same key is listed twice")
        keys.add(entry.key)

        config = KeyConfig(config=entry.config, force=entry.force)
        if configs.setdefault(entry.email, config) != config:
            raise ValueError(
                f"entry {position}: {entry.email} is listed with another config"
            )


def parse(text: str) -> list[ApiKeyEntry]:
    """The file's entries. Raises ValueError naming what is wrong."""
    data = yaml.safe_load(text) or []
    if not isinstance(data, list):
        raise ValueError("the file must be a list of entries")

    entries = []
    for position, item in enumerate(data, start=1):
        try:
            entries.append(ApiKeyEntry.model_validate(item))
        except ValueError as e:
            raise ValueError(f"entry {position}: {e}") from None
    check_entries(entries)

    return entries


class ApiKeysIn(BaseModel):
    """The whole API key file, as `PUT /api_keys` takes it."""

    entries: list[ApiKeyEntry]


class SyncResult(BaseModel):
    """What a sync changed (or, as a dry run, would change), by email: the
    keys themselves are never sent back."""

    added: list[str] = []
    revoked: list[str] = []
    unchanged: list[str] = []
    configs: list[str] = []
    conflicts: list[str] = []
    # What is synced but will not take effect, for the sync to show.
    warnings: list[str] = []


def sync(redis, entries: list[ApiKeyEntry], dry_run: bool = False) -> SyncResult:
    """Make the synced keys and configs in Redis match `entries`.

    A key already in Redis for another email that no sync wrote is a
    conflict: the whole sync is refused rather than taking it over.
    """
    check_entries(entries)
    db = redis.db
    synced = set(db.smembers(SYNCED_KEYS))
    result = SyncResult()

    wanted: dict[str, ApiKeyEntry] = {}
    for entry in entries:
        name = redis.api_key_name(entry.key)
        wanted[name] = entry
        stored = redis.get_api_key_email(entry.key)
        if stored is None:
            result.added.append(entry.email)
        elif stored != entry.email and name not in synced:
            result.conflicts.append(entry.email)
        elif stored != entry.email:
            result.added.append(entry.email)
        else:
            result.unchanged.append(entry.email)

    revoked = synced - set(wanted)
    for name in sorted(revoked):
        result.revoked.append(db.get(name) or "(already gone)")

    configs = {
        entry.email: KeyConfig(config=entry.config, force=entry.force)
        for entry in entries
    }
    result.configs = sorted(
        email for email, config in configs.items() if config.config or config.force
    )

    if dry_run or result.conflicts:
        return result

    pipeline = db.pipeline(transaction=True)
    for name in revoked:
        pipeline.delete(name)
    for entry in entries:
        redis.set_api_key(entry.key, entry.email, remove_plaintext=True, db=pipeline)
    pipeline.delete(SYNCED_KEYS)
    if wanted:
        pipeline.sadd(SYNCED_KEYS, *wanted)
    pipeline.delete(KEY_CONFIGS)
    # Every synced email, with an empty config where it has none, so a lookup
    # also tells a synced user from an unknown one.
    if configs:
        pipeline.hset(
            KEY_CONFIGS,
            mapping={
                email: config.model_dump_json() for email, config in configs.items()
            },
        )
    pipeline.execute()

    return result


def key_config(redis, email: str) -> Optional[KeyConfig]:
    """The config synced for this email (empty where its entries have none),
    or None when no synced key is for it."""
    stored = redis.db.hget(KEY_CONFIGS, email.lower())

    return None if stored is None else KeyConfig(**json.loads(stored))
