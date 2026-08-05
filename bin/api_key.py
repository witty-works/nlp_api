"""Mint, list and revoke API keys without going through the dashboard.

A deployment that runs the NLP API on its own has nothing to write the
`api_key:*` entries the `x-key` header is resolved against, so this is how it
gets its first key. Reads the same environment as the API itself, so it talks to
the same Redis and applies the same HMAC hashing.

    pdm run python -m bin.api_key create user@example.com
    pdm run python -m bin.api_key list
    pdm run python -m bin.api_key delete <key>

Deleting needs the key itself rather than the email: when API_KEY_HMAC_KEY is
set the stored entry is a one-way hash, so the plaintext cannot be recovered
from Redis. `list` prints the stored entries and the email each maps to.
"""

import argparse
import secrets
import sys

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
    create_parser.set_defaults(handler=create)

    list_parser = commands.add_parser("list", help="list stored keys")
    list_parser.set_defaults(handler=list_keys)

    delete_parser = commands.add_parser("delete", help="revoke a key")
    delete_parser.add_argument("api_key", help="the key to revoke")
    delete_parser.set_defaults(handler=delete)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
