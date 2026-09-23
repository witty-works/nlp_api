"""Install the editor script the /textarea page loads.

The page (TEXTAREA_ENABLED) embeds Witty's editor component, which is built in
the browser-extension repository (`packages/editor`) and not kept in this one.
This puts it at app/static/witty-editor.js, together with the licence notices
of the code bundled into it, either from a pinned release or from a local build:

    python bin/fetch_editor.py                          # the pinned release
    python bin/fetch_editor.py --build ~/browser-extension   # a local checkout

Only the standard library, so it runs in the Docker build (--build-arg
TEXTAREA=true) without adding anything to the image. See docs/textarea.md.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPOSITORY = "witty-works/browser-extension"

# The editor release this version of the page is written against, and the
# SHA-256 of each file in it. Update together, from the release's assets.
RELEASE = ""
FILES = {
    "witty-editor.js": "",
    "witty-editor.js.LICENSE.txt": "",
}

DEFAULT_DEST = Path(__file__).resolve().parent.parent / "app" / "static"


class FetchError(Exception):
    pass


def release_url(release: str, name: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/{release}/{name}"


def verify(name: str, data: bytes, expected: str) -> None:
    """Refuse anything but the exact file that was pinned."""
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise FetchError(
            f"{name}: SHA-256 {actual} does not match the pinned {expected}"
        )


def download(release: str, files: dict[str, str], dest: Path, opener=None) -> None:
    if not release or not all(files.values()):
        raise FetchError(
            "No editor release is pinned in bin/fetch_editor.py yet; build one "
            "with --build <browser-extension checkout> instead."
        )

    opener = opener or urllib.request.urlopen
    fetched = {}
    for name, expected in files.items():
        with opener(release_url(release, name)) as response:
            data = response.read()
        verify(name, data, expected)
        fetched[name] = data

    # Only once every file checked out, so a failed run leaves nothing half
    # installed.
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in fetched.items():
        (dest / name).write_bytes(data)


def build(checkout: Path, dest: Path) -> None:
    """Build packages/editor in a browser-extension checkout and copy it here."""
    subprocess.run(
        ["npm", "run", "build", "-w", "@witty-works/editor"], cwd=checkout, check=True
    )

    dist = checkout / "packages" / "editor" / "dist"
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        source = dist / name
        if source.is_file():
            shutil.copyfile(source, dest / name)
        elif name == "witty-editor.js":
            raise FetchError(f"{source} was not built")
        else:
            print(f"warning: {source} missing, not copied", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--build",
        type=Path,
        metavar="CHECKOUT",
        help="build from this browser-extension checkout instead of downloading",
    )
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)

    try:
        if args.build:
            build(args.build.expanduser(), args.dest)
            source = f"a build of {args.build}"
        else:
            download(RELEASE, FILES, args.dest)
            source = f"release {RELEASE}"
    except (FetchError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Installed the editor from {source} into {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
