import json
import argparse

from app.redis_setup import set_up_redis
from app.settings import get_settings

settings = get_settings()
redis = set_up_redis(settings)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--pattern",
        help="Search pattern",
        default="*",
        type=str,
    )

    parser.add_argument(
        "-v",
        "--verbose",
        help="if to enable the verbose output",
        default=False,
        type=bool,
        action=argparse.BooleanOptionalAction,
    )

    return parser.parse_args()


args = parse_args()

i = 0
users = 0
teams = 0
rsa = 0
for key in redis.scan_iter(args.pattern):
    i += 1

    key = key.decode("utf-8")

    if key.startswith("rsa_kid_"):
        print(f"Deleting legacy rsa key {key}")
        redis.delete(key)
        continue

    if key.startswith("rsa_kid:"):
        if args.verbose:
            print(f"Skipping {key}")

        rsa += 1
        continue

    if key.startswith("dashboard-team"):
        if args.verbose:
            print(f"Skipping {key}")

        teams += 1
        continue

    if key.startswith("dashboard-user"):
        users += 1

        configs = redis.get(key)
        configs = json.loads(configs)
        if "organization_id" in configs and configs["organization_id"] is not None:
            organization_id = configs["organization_id"]
            organization_configs = redis.get(organization_id)
            if organization_configs is None:
                print(f"-> For user {key} organization {organization_id} is missing")
                continue

        if args.verbose:
            print(f"For user {key} organization {organization_id} found")
        continue

    print(f"Deleting legacy key {key}")
    redis.delete(key)

print(f"Analyzed {i} keys\n\nusers: {users}\nteams: {teams}\nrsa keys: {rsa}")
