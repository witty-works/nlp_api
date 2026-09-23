"""Install the editor script the /textarea page loads.

The page (TEXTAREA_ENABLED) embeds Witty's editor component, published on npm
as @witty-works/editor and built in the browser-extension repository
(`packages/editor`). It is not kept in this repository. This puts it at
app/static/witty-editor.js, with its licence next to it, either from the
pinned npm release or from a local build:

    python bin/fetch_editor.py                          # the pinned release
    python bin/fetch_editor.py --build ~/browser-extension   # a local checkout

Only the standard library, and no npm: it downloads the package tarball from
the registry and checks it against the integrity npm published for it, so it
runs in the Docker build (--build-arg TEXTAREA=true) without adding anything to
the image. See docs/textarea.md.
"""

import argparse
import base64
import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

PACKAGE = "@witty-works/editor"

# The release this version of the page is written against, and its integrity
# as the registry publishes it: `npm view @witty-works/editor@<version>
# dist.integrity`. Update the two together.
VERSION = "2.0.1"
INTEGRITY = (
    "sha512-vLrVbA166xphUIm/3WmVm0ow6HhT1ZwcTORfMoLHHmP6eVeP6sdiTdfyT3hvw/Wd3tjf"
    "FuOoRdSzwmW2Vh5BeQ=="
)

SCRIPT = "witty-editor.js"
NOTICES = "witty-editor.js.LICENSE.txt"

# Where each file is taken from inside the package, in order of preference:
# the notices of everything bundled into the script where the package ships
# them, the package's own licence otherwise.
SOURCES = {
    SCRIPT: ["package/dist/witty-editor.js"],
    NOTICES: ["package/dist/witty-editor.js.LICENSE.txt", "package/LICENSE"],
}

DEFAULT_DEST = Path(__file__).resolve().parent.parent / "app" / "static"


class FetchError(Exception):
    pass


def tarball_url(package: str, version: str) -> str:
    name = package.rsplit("/", 1)[-1]
    return f"https://registry.npmjs.org/{package}/-/{name}-{version}.tgz"


def verify(data: bytes, integrity: str) -> None:
    """Refuse anything but the exact tarball that was pinned."""
    algorithm, _, expected = integrity.partition("-")
    if algorithm != "sha512" or not expected:
        raise FetchError(f"unsupported integrity {integrity!r}, expected sha512-…")

    actual = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if actual != expected:
        raise FetchError(
            f"the tarball's integrity sha512-{actual} does not match the pinned "
            f"{integrity}"
        )


def unpack(data: bytes) -> dict[str, bytes]:
    """The files the page needs, read by exact name and never extracted as a
    tree, so nothing in the archive decides where anything is written."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        names = set(archive.getnames())
        for target, candidates in SOURCES.items():
            source = next((name for name in candidates if name in names), None)
            if source is None:
                raise FetchError(f"the package has none of {', '.join(candidates)}")
            files[target] = archive.extractfile(source).read()

    return files


def download(
    package: str, version: str, integrity: str, dest: Path, opener=None
) -> None:
    if not version or not integrity:
        raise FetchError(
            "No editor release is pinned in bin/fetch_editor.py; build one with "
            "--build <browser-extension checkout> instead."
        )

    opener = opener or urllib.request.urlopen
    with opener(tarball_url(package, version)) as response:
        data = response.read()

    verify(data, integrity)
    files = unpack(data)

    # Only once the tarball checked out, so a failed run leaves nothing half
    # installed.
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (dest / name).write_bytes(content)


def build(checkout: Path, dest: Path) -> None:
    """Build packages/editor in a browser-extension checkout and copy it here."""
    subprocess.run(
        ["npm", "run", "build", "-w", PACKAGE], cwd=checkout, check=True
    )

    editor = checkout / "packages" / "editor"
    script = editor / "dist" / SCRIPT
    if not script.is_file():
        raise FetchError(f"{script} was not built")

    notices = next(
        (
            path
            for path in (
                editor / "dist" / NOTICES,
                editor / "LICENSE",
                checkout / "LICENSE",
            )
            if path.is_file()
        ),
        None,
    )

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(script, dest / SCRIPT)
    if notices is None:
        print("warning: no licence file found to copy", file=sys.stderr)
    else:
        shutil.copyfile(notices, dest / NOTICES)


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
            download(PACKAGE, VERSION, INTEGRITY, args.dest)
            source = f"{PACKAGE}@{VERSION}"
    except (FetchError, OSError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Installed the editor from {source} into {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
