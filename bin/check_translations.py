#!/usr/bin/env python3
"""Check translation files with the Witty NLP API.

Reads every string from translation files, sends each one to the API's
/v2.4/check with one config, and reports what the API flags, by file and key.
The config is Witty's own style, config/witty.json, unless --config names
another, so every repository's texts are checked the same way.

Formats:
  .php   Laravel language files (`return [...]`), read with the `php` binary
  .json  flat or nested JSON, including WebExtension messages.json
         ({"key": {"message": "..."}})
  .po    gettext catalogues (msgstr, or msgid where msgstr is empty)

The language of a file comes from --lang, or else from its path: a directory
or file named de, fr, en, de_CH, de-CH and so on.

Usage:
  python3 bin/check_translations.py resources/lang --api https://api.example.org
  python3 bin/check_translations.py _locales --format json --cache review.jsonl

Needs only Python's standard library, and `php` for Laravel files, so it runs
from a checkout of this repository without `uv sync`.

Authentication: an API key in WITTY_API_KEY (or --key-env NAME) is sent as
x-key, over https or to an API on this machine only, and redirects are not
followed. A local API started with REQUIRE_AUTH=false needs none.

Laravel files are PHP and are run to be read: check only files you trust.

Exit status: 0 no findings, 1 findings, 2 a file could not be read or a
request failed. A file whose path names no language is skipped with a note.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Witty's own style: the config its repositories check their texts with.
WITTY_CONFIG = Path(__file__).resolve().parent.parent / "config" / "witty.json"

LANGS = ("de", "en", "fr")
LANG_PART = re.compile(r"^(de|en|fr)(?:[_-][A-Za-z]{2})?$")

# Placeholders the API should not read as words: Laravel (:name), ICU and
# i18next ({name}, {{name}}), printf (%s, %1$s), WebExtension ($NAME$).
PLACEHOLDER = re.compile(
    r"\{\{[^}]*\}\}|\{[^}]*\}|(?<![\w:]):[A-Za-z_]\w*|%(?:\d+\$)?[sdif]|\$[A-Z_][A-Z0-9_]*\$"
)
TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"[ \t]+")

PHP_DUMP = (
    "$x = include $argv[1];"
    "echo json_encode(is_array($x) ? $x : [], JSON_UNESCAPED_UNICODE);"
)


@dataclass
class Entry:
    file: Path
    key: str
    lang: str
    source: str
    text: str
    findings: list = field(default_factory=list)
    error: str | None = None


def flatten(value, prefix=""):
    if isinstance(value, dict):
        if set(value) >= {"message"} and isinstance(value["message"], str):
            yield prefix, value["message"]  # WebExtension messages.json
            return
        for k, v in value.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from flatten(v, f"{prefix}.{i}")
    elif isinstance(value, str):
        yield prefix, value


def read_php(path: Path):
    out = subprocess.run(
        # Absolute, so a file named like an option (`-v.php`) is read as a file.
        ["php", "-r", PHP_DUMP, str(path.resolve())],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return flatten(json.loads(out.stdout or "{}"))


def read_json(path: Path):
    return flatten(json.loads(path.read_text(encoding="utf-8")))


def po_unquote(line: str) -> str:
    return json.loads(line) if line.startswith('"') else ""


def read_po(path: Path):
    """The entries of a gettext catalogue as (msgid, text): the translation,
    or the msgid where there is none yet. Of a plural entry the singular
    translation (`msgstr[0]`)."""
    msgid = msgstr = None
    target = None
    for raw in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw.strip()
        if line.startswith("msgid "):
            if msgid:
                yield msgid, msgstr or msgid
            msgid, msgstr, target = po_unquote(line[6:]), "", "id"
        elif line.startswith(("msgstr ", "msgstr[0] ")):
            msgstr, target = po_unquote(line.split(" ", 1)[1]), "str"
        elif line.startswith(("msgid_plural ", "msgstr[", "msgctxt ")):
            target = None
        elif line.startswith('"') and target:
            if target == "id":
                msgid += po_unquote(line)
            else:
                msgstr += po_unquote(line)
        elif not line:
            if msgid:
                yield msgid, msgstr or msgid
            msgid = msgstr = target = None


READERS = {".php": read_php, ".json": read_json, ".po": read_po}


def language_of(path: Path, override: str | None) -> str | None:
    if override:
        return override
    for part in reversed([path.stem, *path.parent.parts]):
        m = LANG_PART.match(part)
        if m:
            return m.group(1)
    return None


def clean(text: str) -> str:
    text = TAG.sub(" ", text)
    text = PLACEHOLDER.sub("", text)
    return SPACES.sub(" ", text).strip()


def collect(paths, lang, exclude) -> tuple[list[Entry], list[str], list[str]]:
    """The strings to check, the files that could not be read, and notes on
    files skipped as in no language."""
    entries, problems, notes = [], [], []
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(
                f for f in p.rglob("*") if f.suffix in READERS and f.is_file()
            )
        else:
            files.append(p)
    for f in files:
        file_lang = language_of(f, lang)
        if file_lang not in LANGS:
            notes.append(f"{f}: language unknown, skipped (use --lang)")
            continue
        try:
            items = list(READERS[f.suffix](f))
        except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
            problems.append(f"{f}: could not be read: {e}")
            continue
        for key, source in items:
            if any(x.search(key) for x in exclude):
                continue
            text = clean(source)
            if re.search(r"[^\W\d_]{2,}", text):
                entries.append(Entry(f, key, file_lang, source, text))
    return entries, problems, notes


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the x-key header to wherever it points."""

    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def may_send_key(api: str) -> bool:
    """An API key goes over https only, or to an API on this machine."""
    url = urllib.parse.urlsplit(api)
    return url.scheme == "https" or (
        url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
    )


def check(entry: Entry, api: str, config: dict, key: str | None, timeout: int) -> Entry:
    body = json.dumps(
        {"text": entry.text, "lang": entry.lang, "config": config}
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "witty-check-translations",
    }
    if key:
        headers["x-key"] = key
    req = urllib.request.Request(f"{api.rstrip('/')}/v2.4/check", body, headers)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            answer = json.load(r)
    except (OSError, http.client.HTTPException, ValueError) as e:
        # OSError covers URLError, timeouts and a dropped connection.
        entry.error = str(e)
        return entry
    for res in answer.get("results", []):
        # gravity null without alternatives is positive feedback.
        if res.get("gravity") is None and not res.get("alternatives"):
            continue
        entry.findings.append(
            {
                "text": res.get("text"),
                "category": res.get("category"),
                "subcategory": res.get("subcategory"),
                "label": res.get("label"),
                "gravity": res.get("gravity"),
                "alternatives": [
                    a.get("text") for a in res.get("alternatives", []) if a.get("text")
                ],
            }
        )
    return entry


def report_markdown(entries: list[Entry], base: Path) -> str:
    lines = []
    current = None
    for e in entries:
        if not e.findings:
            continue
        rel = e.file.relative_to(base) if e.file.is_relative_to(base) else e.file
        if rel != current:
            current = rel
            lines.append(f"\n## {rel}\n")
        lines.append(f"- **`{e.key}`**: {e.source}")
        for f in e.findings:
            alts = ", ".join(f["alternatives"][:5]) or "no alternative"
            lines.append(
                f"  - \"{f['text']}\" ({f['label'] or f['subcategory']}): {alts}"
            )
    return "\n".join(lines).lstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", help="files or directories")
    ap.add_argument("--api", default="http://127.0.0.1:8000", help="NLP API base URL")
    ap.add_argument(
        "--config",
        default=str(WITTY_CONFIG),
        help="JSON file with the check config (default: config/witty.json)",
    )
    ap.add_argument("--lang", choices=LANGS, help="language of all files")
    ap.add_argument(
        "--exclude-key",
        action="append",
        default=[],
        metavar="REGEX",
        help="leave out keys matching REGEX (repeatable)",
    )
    ap.add_argument(
        "--key-env",
        default="WITTY_API_KEY",
        help="environment variable with the API key",
    )
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument(
        "--workers", type=int, default=1, help="parallel requests (default 1)"
    )
    ap.add_argument(
        "--cache",
        metavar="FILE",
        help="JSON lines file of answered strings; a rerun skips them",
    )
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    # Cached answers count only for the config they were given with.
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()[:16]
    exclude = [re.compile(x) for x in args.exclude_key]

    entries, problems, notes = collect(args.paths, args.lang, exclude)
    key = os.environ.get(args.key_env) or None
    if key and not may_send_key(args.api):
        print(
            f"{args.key_env} is set, but {args.api} is neither https nor local: not sending it",
            file=sys.stderr,
        )
        return 2
    done = {}
    if args.cache and Path(args.cache).exists():
        for line in Path(args.cache).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a line cut off by an interrupted run
            if (
                isinstance(row, dict)
                and row.get("config") == config_hash
                and "findings" in row
            ):
                done[(row["file"], row["key"], row["text"])] = row["findings"]
    todo = []
    for e in entries:
        cached = done.get((str(e.file), e.key, e.text))
        if cached is None:
            todo.append(e)
        else:
            e.findings = cached
    cache = open(args.cache, "a", encoding="utf-8") if args.cache else None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for e in pool.map(
                lambda e: check(e, args.api, config, key, args.timeout), todo
            ):
                if cache and not e.error:
                    cache.write(
                        json.dumps(
                            {
                                "file": str(e.file),
                                "key": e.key,
                                "text": e.text,
                                "config": config_hash,
                                "findings": e.findings,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    cache.flush()
    finally:
        if cache:
            cache.close()

    failed = [e for e in entries if e.error]
    problems += [f"{e.file} {e.key}: {e.error}" for e in failed[:10]]
    if len(failed) > 10:
        problems.append(f"... and {len(failed) - 10} more requests failed")

    if args.format == "json":
        print(
            json.dumps(
                [
                    {
                        "file": str(e.file),
                        "key": e.key,
                        "lang": e.lang,
                        "source": e.source,
                        "findings": e.findings,
                    }
                    for e in entries
                    if e.findings
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(report_markdown(entries, Path.cwd()), end="")

    flagged = sum(1 for e in entries if e.findings)
    print(
        f"{len(entries)} strings checked, {flagged} with findings, {len(failed)} failed",
        file=sys.stderr,
    )
    for p in notes + problems:
        print(p, file=sys.stderr)
    if failed or problems:
        return 2
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
