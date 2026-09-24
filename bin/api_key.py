"""Mint, list and revoke API keys without going through the dashboard.

A deployment that runs the NLP API on its own has nothing to write the
`api_key:*` entries the `x-key` header is resolved against, so this is how it
gets its first key. Reads the same environment as the API itself, so it talks to
the same Redis and applies the same HMAC hashing.

    pdm run python -m bin.api_key create user@example.com
    pdm run python -m bin.api_key list
    pdm run python -m bin.api_key delete <key>

Or into a local API key file, synced to the API with bin/sync_api_keys.py
(see app/api_keys.py) rather than written to Redis:

    pdm run python -m bin.api_key create user@example.com --file api_keys.yaml \
        --note "Jane Doe (ACME), HR pilot until 2026-12"

Deleting needs the key itself rather than the email: when API_KEY_HMAC_KEY is
set the stored entry is a one-way hash, so the plaintext cannot be recovered
from Redis. `list` prints the stored entries and the email each maps to.
"""

import argparse
import os
import secrets
import sys

import yaml

from app.api_keys import ApiKeyEntry, parse

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
