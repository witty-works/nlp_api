"""Move organisation configs stored under their bare id to the prefixed key
the API now uses (`dashboard-organization:<id>`).

Until this has run the API still reads such a config, but only one that is a
JSON object naming its own key as `id`; this moves exactly those, so nothing
else in Redis is touched. A config already stored under the prefix is newer:
the bare copy is then deleted, not moved. Run it once, wherever `REDIS_HOST`
points at the deployment's Redis, with `--dry-run` first to see the count.

    uv run python -m bin.migrate_organization_keys --dry-run
    uv run python -m bin.migrate_organization_keys
"""

import argparse
import sys

from app.redis import Redis
from app.settings import get_settings


def migrate(redis: Redis, dry_run: bool = False) -> tuple[int, int]:
    """Moved and dropped bare-id configs, as counts."""
    moved = dropped = 0
    for name in list(redis.db.scan_iter()):
        if isinstance(name, bytes):  # pragma: no cover
            name = name.decode("utf-8")
        # Every other key the API writes has a prefix with a colon.
        if ":" in name or redis.db.type(name) != "string":
            continue
        value = redis.legacy_organization_configs(name)
        if value is None:
            continue

        prefixed = redis.get_organization_key(name)
        if redis.db.exists(prefixed):
            dropped += 1
        else:
            moved += 1
            if not dry_run:
                redis.db.set(prefixed, value)
        if not dry_run:
            redis.db.delete(name)

    return moved, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count, change nothing")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.redis_host:
        print(
            "error: REDIS_HOST is not set, so there is no deployment Redis to migrate",
            file=sys.stderr,
        )
        return 1

    moved, dropped = migrate(Redis.factory(settings), args.dry_run)
    verb = "would be" if args.dry_run else "were"
    print(f"{moved} organisation config(s) {verb} moved to the prefixed key")
    print(f"{dropped} bare-id copy(ies) of a prefixed config {verb} deleted")

    return 0


if __name__ == "__main__":
    sys.exit(main())
