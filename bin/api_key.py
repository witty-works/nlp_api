"""Mint, list and revoke API keys without going through the dashboard.

A deployment that runs the NLP API on its own has nothing to write the
`api_key:*` entries the `x-key` header is resolved against, so this is how it
gets its first key. Reads the same environment as the API itself, so it talks to
the same Redis and applies the same HMAC hashing.

    uv run python -m bin.api_key create user@example.com
    uv run python -m bin.api_key list
    uv run python -m bin.api_key delete <key>
    uv run python -m bin.api_key rehash

Or into a local API key file, synced to the API with bin/sync_api_keys.py
(see app/api_keys.py) rather than written to Redis:

    uv run python -m bin.api_key create user@example.com --file api_keys.yaml \
        --note "Jane Doe (ACME), HR pilot until 2026-12"

Deleting needs the key itself rather than the email: when API_KEY_HMAC_KEY is
set the stored entry is a one-way hash, so the plaintext cannot be recovered
from Redis. `list` prints the stored entries and the email each maps to.
"""

import argparse
import os
import re
import secrets
import sys

import yaml
from redis.exceptions import WatchError

from app.api_keys import SYNCED_KEYS, ApiKeyEntry, parse

from app.redis import Redis
from app.settings import get_settings


def create(redis: Redis, args) -> int:
    api_key = args.api_key or secrets.token_urlsafe(32)

    if redis.get_api_key_email(api_key):
        print("error: that API key already exists", file=sys.stderr)
        return 1

    redis.set_api_key(api_key, args.email)

    print(api_key)
    if not args.api_key:
        print(
            f"\nMapped to {args.email}. Store it now — it is not recoverable "
            "from Redis when API_KEY_HMAC_KEY is set.",
            file=sys.stderr,
        )

    return 0


def create_in_file(args) -> int:
    """Append an entry for a new key to the local API key file, keeping the
    rest of it (and its comments) as written."""
    try:
        with open(args.file, encoding="utf-8") as f:
            before = f.read()
    except FileNotFoundError:
        before = ""

    api_key = args.api_key or secrets.token_urlsafe(32)
    note = "".join(f"# {line}\n" for line in (args.note or args.email).splitlines())
    try:
        entries = parse(before)
        entry = ApiKeyEntry(email=args.email, key=api_key)
    except ValueError as e:
        print(f"error: {args.file}: {e}", file=sys.stderr)
        return 1

    if any(e.email == entry.email and (e.config or e.force) for e in entries):
        print(
            f"error: {entry.email} has a config in {args.file}; add the key by "
            "hand with the same config",
            file=sys.stderr,
        )
        return 1
    if any(e.key == api_key for e in entries):
        print("error: that API key already exists", file=sys.stderr)
        return 1

    # Dumped, not formatted by hand, so an email with YAML characters in it
    # is quoted rather than breaking the file.
    text = note + yaml.safe_dump(
        [{"email": entry.email, "key": api_key}], sort_keys=False, allow_unicode=True
    )
    if before and not before.endswith("\n\n"):
        text = ("\n" if before.endswith("\n") else "\n\n") + text
    try:
        parse(before + text)
    except ValueError as e:
        print(f"error: {args.file}: {e}", file=sys.stderr)
        return 1

    # The file holds keys: only its owner may read it, even when it is new.
    descriptor = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as f:
        f.write(text)

    print(api_key)
    print(
        f"\nAdded {entry.email} to {args.file}. It takes effect with the next "
        "bin/sync_api_keys.py.",
        file=sys.stderr,
    )

    return 0


def list_keys(redis: Redis, args) -> int:
    found = 0
    for key in sorted(redis.db.scan_iter("api_key:*")):
        if isinstance(key, bytes):  # pragma: no cover
            key = key.decode("utf-8")

        found += 1
        print(f"{key.removeprefix('api_key:')}\t{redis.db.get(key)}")

    if not found:
        print("no API keys stored", file=sys.stderr)

    return 0


def delete(redis: Redis, args) -> int:
    if not redis.get_api_key_email(args.api_key):
        print("error: no such API key", file=sys.stderr)
        return 1

    redis.delete_api_key(args.api_key)

    return 0


# What set_api_key stores under when API_KEY_HMAC_KEY is set.
DIGEST = re.compile(r"[0-9a-f]{64}")


def rehash(redis: Redis, args) -> int:
    """Store every key kept as written under its HMAC digest instead, for a
    deployment that set API_KEY_HMAC_KEY after minting keys: with the secret
    set, those entries no longer resolve.

    Each entry moves in one watched transaction, so a key revoked meanwhile
    is not brought back. A plaintext entry whose digest already maps to
    another email is a conflict and left as it is: the digest is the newer
    write. A key that is itself 64 lowercase hex characters cannot be told
    from a digest and is left alone; both are counted in the output, which
    never names a key."""
    if not redis.settings.api_key_hmac_key:
        print("error: API_KEY_HMAC_KEY is not set", file=sys.stderr)
        return 1

    moved, conflicts, digest_like = 0, 0, 0
    for name in list(redis.db.scan_iter("api_key:*")):
        if isinstance(name, bytes):  # pragma: no cover
            name = name.decode("utf-8")
        api_key = name.removeprefix("api_key:")
        if DIGEST.fullmatch(api_key):
            # set_api_key never writes a 64-hex plaintext name with the secret
            # set, so only an entry that does not resolve can be one.
            if redis.db.get(redis.api_key_name(api_key)) is None:
                digest_like += 1
            continue

        outcome = _rehash_one(redis, name, api_key)
        moved += outcome == "moved"
        conflicts += outcome == "conflict"

    print(f"{moved} key(s) now stored as HMAC digests", file=sys.stderr)
    if digest_like:
        print(
            f"{digest_like} "
            + ("entry looks" if digest_like == 1 else "entries look")
            + " like a digest but may be a 64-character hex key stored as"
            " written: check with `list`",
            file=sys.stderr,
        )
    if conflicts:
        print(
            f"{conflicts} conflict(s): a key stored as written and as a digest"
            " maps to two emails; both left as they are",
            file=sys.stderr,
        )
        return 1

    return 0


def _rehash_one(redis: Redis, name: str, api_key: str) -> str:
    """Move one plaintext entry to its digest: "moved", "conflict" or "gone"."""
    digest_name = redis.api_key_name(api_key)
    for _ in range(3):
        with redis.db.pipeline() as pipeline:
            try:
                pipeline.watch(name, digest_name, SYNCED_KEYS)
                email = pipeline.get(name)
                if email is None:
                    return "gone"
                current = pipeline.get(digest_name)
                if current is not None and current != email:
                    return "conflict"
                synced = pipeline.sismember(SYNCED_KEYS, name)

                pipeline.multi()
                pipeline.set(digest_name, email)
                pipeline.delete(name)
                # A key the file sync wrote stays the file's.
                if synced:
                    pipeline.srem(SYNCED_KEYS, name)
                    pipeline.sadd(SYNCED_KEYS, digest_name)
                pipeline.execute()
                return "moved"
            except WatchError:
                continue

    raise RuntimeError("an API key kept changing during rehash; run it again")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    create_parser = commands.add_parser("create", help="mint a key for an email")
    create_parser.add_argument("email", help="the email the key resolves to")
    create_parser.add_argument(
        "--api-key",
        help="use this key instead of generating one",
        default=None,
    )
    create_parser.add_argument(
        "--file",
        help="add it to this local API key file instead of Redis",
        default=None,
    )
    create_parser.add_argument(
        "--note",
        help="who the key is for, written as the entry's comment (with --file)",
        default=None,
    )
    create_parser.set_defaults(handler=create)

    list_parser = commands.add_parser("list", help="list stored keys")
    list_parser.set_defaults(handler=list_keys)

    delete_parser = commands.add_parser("delete", help="revoke a key")
    delete_parser.add_argument("api_key", help="the key to revoke")
    delete_parser.set_defaults(handler=delete)

    rehash_parser = commands.add_parser(
        "rehash",
        help="store keys kept as written as HMAC digests (needs API_KEY_HMAC_KEY)",
    )
    rehash_parser.set_defaults(handler=rehash)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "create" and args.file:
        return create_in_file(args)

    settings = get_settings()

    if not settings.redis_host:
        print(
            "error: REDIS_HOST is not set, so this would write to the in-memory "
            "Redis the API falls back to and vanish on exit",
            file=sys.stderr,
        )
        return 1

    return args.handler(Redis.factory(settings), args)


if __name__ == "__main__":
    sys.exit(main())
