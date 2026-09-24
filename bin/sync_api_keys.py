"""Sync a local API key file to the NLP API.

The file (see app/api_keys.py and api_keys.example.yaml) stays on your
machine; this sends it to the API's `PUT /api_keys`, which makes the server's
synced keys match it. It shows what would change first and asks before
changing anything:

    pdm run python -m bin.sync_api_keys api_keys.yaml --url https://nlp-api.example
    pdm run python -m bin.sync_api_keys api_keys.yaml --url … --yes   # no question

The API's management credentials (API_DOCS_USERNAME / API_DOCS_PASSWORD on the
server) come from NLP_API_USERNAME and NLP_API_PASSWORD, or are asked for.
"""

import argparse
import base64
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from app.api_keys import parse


def put(
    url: str, auth: str, entries: list, dry_run: bool, allow_empty: bool = False
) -> dict:
    body = json.dumps({"entries": entries}).encode("utf-8")
    query = urllib.parse.urlencode(
        {"dry_run": str(dry_run).lower(), "allow_empty": str(allow_empty).lower()}
    )
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api_keys?{query}",
        data=body,
        method="PUT",
        headers={"Content-Type": "application/json", "Authorization": auth},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def report(result: dict, dry_run: bool) -> bool:
    """Print what changed (or would); whether anything does."""
    will = "would be " if dry_run else ""
    for email in result["added"]:
        print(f"  + {email}: key {will}added")
    for email in result["revoked"]:
        print(f"  - {email}: key {will}revoked")
    for move in result.get("moved", []):
        print(f"  ~ key {will}moved: {move}")
    for email in result.get("unmanaged", []):
        print(f"  ! {email}: key was not added by a sync, left as it is")
    print(f"  = {len(result['unchanged'])} keys unchanged")
    if result["configs"]:
        print(f"  config for: {', '.join(result['configs'])}")
    for warning in result.get("warnings", []):
        print(f"  ! {warning}")

    return bool(result["added"] or result["revoked"] or result.get("moved"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("file", help="the local API key file")
    parser.add_argument(
        "--url", default=os.environ.get("NLP_API_URL"), help="the API's base URL"
    )
    parser.add_argument("--yes", action="store_true", help="sync without asking first")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="sync an empty file, which revokes every synced key",
    )
    args = parser.parse_args()

    if not args.url:
        print("error: --url (or NLP_API_URL) is needed", file=sys.stderr)
        return 1
    url = urllib.parse.urlparse(args.url)
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    if url.scheme != "https" and not (url.scheme == "http" and local):
        print("error: the file holds keys; send it over https only", file=sys.stderr)
        return 1

    try:
        with open(args.file, encoding="utf-8") as f:
            entries = parse(f.read())
    except (OSError, ValueError) as e:
        print(f"error: {args.file}: {e}", file=sys.stderr)
        return 1

    username = os.environ.get("NLP_API_USERNAME") or input("Management username: ")
    password = os.environ.get("NLP_API_PASSWORD") or getpass.getpass("Password: ")
    auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    payload = [entry.model_dump() for entry in entries]

    try:
        planned = put(args.url, auth, payload, True, args.allow_empty)
        print(f"{len(entries)} keys in {args.file}:")
        changes = report(planned, dry_run=True)
        if not changes and not planned["configs"]:
            print("Nothing to change in the keys; configs are written anyway.")
        if not args.yes and input("Sync? [y/N] ").strip().lower() != "y":
            print("Nothing synced.")
            return 1

        report(put(args.url, auth, payload, False, args.allow_empty), dry_run=False)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        print(f"error: {e.code} {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: {e.reason}", file=sys.stderr)
        return 1

    print("Synced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
