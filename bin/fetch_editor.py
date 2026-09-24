"""Install the editor script the /textarea page loads.

The page (TEXTAREA_ENABLED) embeds Witty's editor component, published on npm
as @witty-works/editor and built in the browser-extension repository
(`packages/editor`). It is not kept in this repository. This puts it at
app/static/witty-editor.js, with its licence next to it, either from the
pinned npm release or from a local build:

    python bin/fetch_editor.py                          # the pinned release
    python bin/fetch_editor.py --build ~/browser-extension   # a local checkout

Moving the pin to a new version is the one step that needs npm:

    python bin/fetch_editor.py --pin 2.0.2

installs that version into a throwaway npm project, has `npm audit signatures`
verify its registry signature and provenance, checks the provenance names the
browser-extension repository's publish workflow and the version's own tag, and
only then writes the version and its integrity into this file.

Only the standard library, and no npm: it downloads the package tarball from
the registry and checks it against the integrity npm published for it, so it
runs in the Docker build (--build-arg TEXTAREA=true) without adding anything to
the image. See docs/textarea.md.
"""

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PACKAGE = "@witty-works/editor"

# The release this version of the page is written against, and its integrity
# as the registry publishes it: `npm view @witty-works/editor@<version>
# dist.integrity`. Update the two together.
VERSION = "2.3.0"
INTEGRITY = (
    "sha512-RH+uBVloBK1UdWIddubsqPet4yN9uPO5NoaGoPdY"
    "4ObfLpFOVEQmH3ZjVFT/0W7Pc6DQ9dZRoDzKxsl2ftpXSw=="
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

# Seconds without progress before a download gives up, so a stalled registry
# fails a Docker build instead of hanging it.
TIMEOUT = 60

# Where a version has to come from before --pin accepts it: built by this
# workflow in this repository, from the tag named after the version.
PROVENANCE_REPOSITORY = "https://github.com/witty-works/browser-extension"
PROVENANCE_WORKFLOW = ".github/workflows/publish-editor.yaml"
SLSA_PROVENANCE = "https://slsa.dev/provenance/v1"


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
    with opener(tarball_url(package, version), timeout=TIMEOUT) as response:
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


def check_provenance(audit: dict, package: str, version: str) -> str:
    """The commit a version was built from, if `npm audit signatures` verified
    it and its provenance names the expected workflow and tag."""
    if audit.get("invalid") or audit.get("missing"):
        raise FetchError(
            "npm audit signatures reports invalid or missing signatures: "
            + json.dumps({k: audit.get(k) for k in ("invalid", "missing")})
        )

    entry = next(
        (
            item
            for item in audit.get("verified", [])
            if item.get("name") == package and item.get("version") == version
        ),
        None,
    )
    if entry is None:
        raise FetchError(f"{package}@{version} is not among the verified packages")

    statement = None
    for bundle in entry.get("attestationBundles") or []:
        if bundle.get("predicateType") == SLSA_PROVENANCE:
            payload = bundle["bundle"]["dsseEnvelope"]["payload"]
            statement = json.loads(base64.b64decode(payload))
    if statement is None:
        raise FetchError(f"{package}@{version} has no verified provenance")

    build = statement["predicate"]["buildDefinition"]
    workflow = build["externalParameters"]["workflow"]
    expected = {
        "repository": PROVENANCE_REPOSITORY,
        "path": PROVENANCE_WORKFLOW,
        "ref": f"refs/tags/{version}",
    }
    actual = {key: workflow.get(key) for key in expected}
    if actual != expected:
        raise FetchError(
            f"{package}@{version} was built by {actual}, expected {expected}"
        )

    return build["resolvedDependencies"][0]["digest"]["gitCommit"]


def rewrite_pin(source: str, version: str, integrity: str) -> str:
    """This script's text with VERSION and INTEGRITY replaced."""
    half = len(integrity) // 2
    source, versions = re.subn(
        r'^VERSION = "[^"]*"$', f'VERSION = "{version}"', source, flags=re.M
    )
    source, integrities = re.subn(
        r"^INTEGRITY = \(\n.*?\n\)$",
        f'INTEGRITY = (\n    "{integrity[:half]}"\n    "{integrity[half:]}"\n)',
        source,
        flags=re.M | re.S,
    )
    if versions != 1 or integrities != 1:
        raise FetchError("could not find VERSION and INTEGRITY to rewrite")

    return source


def pin(version: str, script: Path, run=subprocess.run) -> tuple[str, str]:
    """Verify a version with npm and write it into this script."""
    if shutil.which("npm") is None:
        raise FetchError("--pin needs npm, to verify signatures and provenance")

    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        (project / "package.json").write_text('{"name": "pin-check", "private": true}')

        def npm(*args: str) -> str:
            try:
                return run(
                    ["npm", *args], cwd=project, check=True, capture_output=True,
                    text=True,
                ).stdout
            except subprocess.CalledProcessError as error:
                reason = (error.stderr or error.stdout or "").strip().splitlines()
                raise FetchError(
                    f"npm {args[0]} failed: " + " ".join(reason[-3:])
                ) from error

        # --ignore-scripts: nothing from the package runs, here or anywhere.
        # --prefer-online: a version published minutes ago is not in npm's
        # cached metadata yet.
        npm(
            "install", "--ignore-scripts", "--no-audit", "--no-fund",
            "--prefer-online", "--save-exact", f"{PACKAGE}@{version}",
        )
        audit = npm("audit", "signatures", "--json", "--include-attestations")
        commit = check_provenance(json.loads(audit), PACKAGE, version)

        lock = json.loads((project / "package-lock.json").read_text())
        integrity = lock["packages"][f"node_modules/{PACKAGE}"]["integrity"]

    script.write_text(rewrite_pin(script.read_text(), version, integrity))
    return integrity, commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--build",
        type=Path,
        metavar="CHECKOUT",
        help="build from this browser-extension checkout instead of downloading",
    )
    parser.add_argument(
        "--pin",
        metavar="VERSION",
        help="verify this version with npm and pin it in this script (needs npm)",
    )
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)

    try:
        if args.pin:
            integrity, commit = pin(args.pin, Path(__file__).resolve())
            print(
                f"Pinned {PACKAGE}@{args.pin} ({integrity}), built by "
                f"{PROVENANCE_WORKFLOW} from {commit}. Run this script again "
                "to install it, and check the page against it."
            )
            return 0

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
