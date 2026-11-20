"""Install the spaCy model wheels, pinned by hash in bin/spacy-models.json.

The models are not in uv.lock: they are wheels on GitHub release pages, not on
a package index, and Dependabot cannot resolve a lock that contains them. They
stay at the version spaCy 3.8 was released with; moving them is a reviewed
change (it changes what is flagged, see AGENTS.md).

    uv run python -m bin.install_spacy_models                 # en, de, fr; lg
    uv run python -m bin.install_spacy_models --size sm --langs en

`uv sync` removes packages that are not in the lock, so run this again after
it, or sync with `uv sync --inexact`. The Docker build uses the
--requirements-out and --models-out options instead of installing.

Standard library only, so the Docker build can run it before anything is
installed.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

PINS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spacy-models.json")
KIND = {"en": "core_web", "de": "core_news", "fr": "core_news"}


def select(langs: str, size: str) -> list[str]:
    """Model names for a comma-separated list of languages and one size, in
    the order en, de, fr."""
    size = size.strip()
    if size not in {"sm", "md", "lg"}:
        raise SystemExit(f"--size must be sm, md or lg, got {size!r}")
    wanted = {lang.strip() for lang in langs.split(",") if lang.strip()}
    unknown = wanted - set(KIND)
    if unknown:
        raise SystemExit(f"no spaCy model for: {', '.join(sorted(unknown))}")
    names = [f"{lang}_{KIND[lang]}_{size}" for lang in KIND if lang in wanted]
    if not names:
        raise SystemExit(f"--langs selected no models: {langs!r}")
    return names


def requirements(names: list[str]) -> str:
    pins = json.load(open(PINS, encoding="utf-8"))["models"]
    return "".join(
        f"{name} @ {pins[name]['url']} --hash=sha256:{pins[name]['sha256']}\n"
        for name in names
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--langs", default="en,de,fr")
    parser.add_argument("--size", default="lg")
    parser.add_argument(
        "--requirements-out",
        help="write a pip requirements file with hashes instead of installing",
    )
    parser.add_argument(
        "--models-out", help="also write the selected model names, comma-separated"
    )
    args = parser.parse_args(argv)

    names = select(args.langs, args.size)
    pinned = requirements(names)

    if args.models_out:
        with open(args.models_out, "w", encoding="utf-8") as f:
            f.write(",".join(names))

    if args.requirements_out:
        with open(args.requirements_out, "w", encoding="utf-8") as f:
            f.write(pinned)
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(pinned)
    try:
        # Into the environment this runs in; --no-deps, as spaCy itself comes
        # from the lock.
        return subprocess.call(
            ["uv", "pip", "install", "--python", sys.executable, "--no-deps",
             "--require-hashes", "--requirement", f.name]
        )  # fmt: skip
    finally:
        os.unlink(f.name)


if __name__ == "__main__":
    sys.exit(main())
