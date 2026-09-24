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
import logging
import re
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from redis.exceptions import WatchError

from app.categories import get_category_keys
from app.models import Config

# Redis: the `api_key:*` entries the last sync wrote, so the next one can
# revoke those it no longer lists, and each email's config.
SYNCED_KEYS = "api_keys_synced"
KEY_CONFIGS = "api_key_configs"


# Config fields a key may not set: the deployment's limits, not a user's
# preferences.
NOT_PER_KEY = {"alternatives_max_count": "the deployment's ALTERNATIVES_MAX_COUNT"}


def describe(error: ValidationError) -> str:
    """A validation error without the input it was about: the input may be a
    key, and this message ends up in a terminal or an HTTP response."""
    return "; ".join(
        (
            ".".join(str(part) for part in detail["loc"]) + ": " + detail["msg"]
            if detail["loc"]
            else detail["msg"]
        )
        for detail in error.errors(include_input=False, include_url=False)
    )


def _checked_config(fields: dict[str, Any], name: str) -> dict[str, Any]:
    """`fields` validated as a request's config and normalised the way the
    request would get them (enums as their values, `"de-CH"` as a list), so
    what is stored is what applies."""
    unknown = sorted(set(fields) - set(Config.model_fields))
    if unknown:
        raise ValueError(f"{name} has no such config option: {', '.join(unknown)}")
    blocked = sorted(set(fields) & set(NOT_PER_KEY))
    if blocked:
        field = blocked[0]
        raise ValueError(f"{name} cannot set {field}: it is {NOT_PER_KEY[field]}")
    # Validated as a request's config would be, so a typo in a value fails
    # before it is sent rather than on the first request that uses it.
    try:
        normalised = Config(**fields).model_dump(mode="json", include=set(fields))
    except ValidationError as error:
        raise ValueError(f"{name}: {describe(error)}") from None
    # A request's config takes any category name, where a typo would silently
    # disable nothing, so those are checked here too. Their order means
    # nothing, so it does not tell two configs apart.
    if "disabled_categories" in normalised:
        categories = sorted(normalised["disabled_categories"] or [])
        unknown = sorted(set(categories) - set(get_category_keys()))
        if unknown:
            raise ValueError(f"{name} has no such category: {', '.join(unknown)}")
        normalised["disabled_categories"] = categories

    return normalised


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


def valid_email(email: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
        raise ValueError("not an email")

    return email.lower()


def valid_key(key: str) -> str:
    # What `bin/api_key.py` mints is 43 characters; anything much shorter is
    # guessable.
    if len(key) < 20 or not re.fullmatch(r"[A-Za-z0-9_\-]+", key):
        raise ValueError("a key needs at least 20 letters, digits, - or _")

    return key


class ApiKeyEntry(KeyConfig):
    model_config = ConfigDict(extra="forbid")

    email: str
    key: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, email: str) -> str:
        return valid_email(email)

    @field_validator("key")
    @classmethod
    def _valid_key(cls, key: str) -> str:
        return valid_key(key)


def check_entries(entries: list[ApiKeyEntry]) -> None:
    """Raises ValueError for a key listed twice or an email with two configs."""
    keys: set[str] = set()
    configs: dict[str, KeyConfig] = {}
    for position, entry in enumerate(entries, start=1):
        if entry.key in keys:
            raise ValueError(f"entry {position}: the same key is listed twice")
        keys.add(entry.key)

        config = KeyConfig.model_construct(config=entry.config, force=entry.force)
        if configs.setdefault(entry.email, config) != config:
            raise ValueError(
                f"entry {position}: {entry.email} is listed with another config"
            )


def parse(text: str) -> list[ApiKeyEntry]:
    """The file's entries. Raises ValueError naming what is wrong, but never
    quoting it: the file holds keys."""
    try:
        data = yaml.safe_load(text) or []
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise ValueError(f"not valid YAML{where}") from None
    if not isinstance(data, list):
        raise ValueError("the file must be a list of entries")

    entries = []
    for position, item in enumerate(data, start=1):
        try:
            entries.append(ApiKeyEntry.model_validate(item))
        except ValidationError as error:
            raise ValueError(f"entry {position}: {describe(error)}") from None
    check_entries(entries)

    return entries


def validate_entries(body: Any) -> list[ApiKeyEntry]:
    """The body of `PUT /api_keys` (`{"entries": [...]}`) as entries. Raises
    ValueError without quoting the input, unlike FastAPI's own 422."""
    if not isinstance(body, dict) or not isinstance(body.get("entries"), list):
        raise ValueError('the body must be {"entries": [...]}')
    entries = []
    for position, item in enumerate(body["entries"], start=1):
        try:
            entries.append(ApiKeyEntry.model_validate(item))
        except ValidationError as error:
            raise ValueError(f"entry {position}: {describe(error)}") from None
    check_entries(entries)

    return entries


class ApiKeysIn(BaseModel):
    """The whole API key file, as `PUT /api_keys` takes it (documentation
    only: the handler validates it with validate_entries)."""

    entries: list[ApiKeyEntry]


class SyncResult(BaseModel):
    """What a sync changed (or, as a dry run, would change), by email: the
    keys themselves are never sent back."""

    added: list[str] = []
    revoked: list[str] = []
    unchanged: list[str] = []
    # A key that moved to another email: "old -> new".
    moved: list[str] = []
    # Keys in the file that were minted some other way (dashboard, CLI,
    # DEFAULT_API_KEY) for the same email: left alone, so deleting them from
    # the file does not revoke them either.
    unmanaged: list[str] = []
    configs: list[str] = []
    conflicts: list[str] = []
    # What is synced but will not take effect, for the sync to show.
    warnings: list[str] = []


class SyncRefused(ValueError):
    pass


def sync(
    redis,
    entries: list[ApiKeyEntry],
    dry_run: bool = False,
    allow_empty: bool = False,
) -> SyncResult:
    """Make the synced keys and configs in Redis match `entries`.

    A key already in Redis for another email that no sync wrote is a
    conflict: the whole sync is refused rather than taking it over. The reads
    and writes are one watched transaction, retried if another sync or a key
    written meanwhile changed what was read.
    """
    check_entries(entries)
    if not entries and not allow_empty:
        raise SyncRefused(
            "no keys listed: syncing that would revoke every synced key"
            " (allow_empty does it anyway)"
        )

    names = [redis.api_key_name(entry.key) for entry in entries]
    plains = [f"api_key:{entry.key}" for entry in entries]
    for _ in range(3):
        with redis.db.pipeline() as pipeline:
            try:
                pipeline.watch(SYNCED_KEYS, *names, *plains)
                result = _sync(redis, pipeline, entries, names, plains, dry_run)
                return result
            except WatchError:
                continue

    raise SyncRefused("the keys changed during the sync three times; try again")


def _sync(redis, pipeline, entries, names, plains, dry_run) -> SyncResult:
    synced = set(pipeline.smembers(SYNCED_KEYS))
    stored = pipeline.mget(names) if names else []
    stored_plain = pipeline.mget(plains) if plains else []
    result = SyncResult()

    written: list[tuple[str, ApiKeyEntry]] = []
    for entry, name, value, plain_value in zip(entries, names, stored, stored_plain):
        current = value or plain_value
        if current is None:
            result.added.append(entry.email)
        elif name not in synced and current != entry.email:
            result.conflicts.append(entry.email)
            continue
        elif name not in synced:
            result.unmanaged.append(entry.email)
            continue
        elif current != entry.email:
            result.moved.append(f"{current} -> {entry.email}")
        else:
            result.unchanged.append(entry.email)
        written.append((name, entry))

    revoked = synced - {name for name, _ in written}
    revoked_emails = pipeline.mget(sorted(revoked)) if revoked else []
    result.revoked = [email or "(already gone)" for email in revoked_emails]

    configs = {
        entry.email: KeyConfig.model_construct(config=entry.config, force=entry.force)
        for entry in entries
    }
    result.configs = sorted(
        email for email, config in configs.items() if config.config or config.force
    )

    if dry_run or result.conflicts:
        pipeline.reset()
        return result

    pipeline.multi()
    for name in revoked:
        pipeline.delete(name)
    for name, entry in written:
        redis.set_api_key(entry.key, entry.email, remove_plaintext=True, db=pipeline)
    pipeline.delete(SYNCED_KEYS)
    if written:
        pipeline.sadd(SYNCED_KEYS, *(name for name, _ in written))
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
    or None when no synced key is for it.

    Checked field by field rather than as a whole: it was valid at the sync,
    and a deploy that renames an option or narrows a value must not fail every
    request of the key's user. What no longer validates is dropped and logged.
    """
    stored = redis.db.hget(KEY_CONFIGS, email.lower())
    if stored is None:
        return None

    data = json.loads(stored)
    known = {}
    for part in ("config", "force"):
        fields = data.get(part) or {}
        known[part] = {
            field: value
            for field, value in fields.items()
            if field in Config.model_fields and _still_valid(field, value)
        }
        dropped = sorted(set(fields) - set(known[part]))
        if dropped:
            logging.getLogger("nlp_api").warning(
                "synced %s for %s no longer valid, ignored: %s",
                part,
                email,
                ", ".join(dropped),
            )

    return KeyConfig.model_construct(**known)


def _still_valid(field: str, value) -> bool:
    try:
        Config.__pydantic_validator__.validate_assignment(Config(), field, value)
    except ValidationError:
        return False

    return True
