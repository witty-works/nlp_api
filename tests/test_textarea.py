"""The /textarea page as this API hosts it.

The editor component the page loads is tested where it is built (the
browser-extension repository, packages/editor); these cover what is decided
here: that the page is opt-in, how it sits behind the key gate, what it serves
without its script, and the page's own contract with the API.
"""

import ast
import base64
import hashlib
import importlib.util
import io
import json
import re
import tarfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, context
from app.routes.textarea import PAGE

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def textarea(monkeypatch, tmp_path):
    """Turn the page on, with a stand-in for the editor script."""
    bundle = tmp_path / "witty-editor.js"
    bundle.write_text("window.WittyEditor = {mount() {}};")
    monkeypatch.setattr("app.routes.textarea.EDITOR_BUNDLE", bundle)
    monkeypatch.setattr(context.settings, "textarea_enabled", True)

    return bundle


@pytest.fixture
def key_gate(monkeypatch):
    context.redis.set_api_key("textarea-key", "default@gmail.com")
    monkeypatch.setattr(context.settings, "require_api_key", True)


def test_off_by_default():
    """A deployment that did not ask for the page does not serve it."""
    assert context.settings.textarea_enabled is False

    with TestClient(app) as client:
        assert client.get("/textarea").status_code == 404
        assert client.get("/textarea/witty-editor.js").status_code == 404


def test_off_is_not_public(key_gate):
    """Behind the gate a disabled page is closed like any unknown path."""
    with TestClient(app) as client:
        assert client.get("/textarea").status_code == 401
        assert client.get("/textarea/witty-editor.js").status_code == 401


def test_page_and_script(textarea):
    with TestClient(app) as client:
        response = client.get("/textarea")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert '<script src="/textarea/witty-editor.js"></script>' in response.text

        response = client.get("/textarea/witty-editor.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript")
        assert response.text == textarea.read_text()


def test_public_when_on_and_checks_still_gated(textarea, key_gate):
    """On is enough: the page loads without a key or a PUBLIC_PATHS entry."""
    body = {"text": "Hey guys, the chairman will be late."}
    assert "/textarea" not in context.settings.public_paths

    with TestClient(app) as client:
        assert client.get("/textarea").status_code == 200
        assert client.get("/textarea/witty-editor.js").status_code == 200

        # The page is open, the checks it makes are not.
        assert client.post("/v2.4/check", json=body).status_code == 401
        response = client.post(
            "/v2.4/check", json=body, headers={"x-key": "textarea-key"}
        )
        assert response.status_code == 200

        # Exact paths only, as for PUBLIC_PATHS.
        assert client.get("/textarea/other.js").status_code == 401


def test_missing_script_says_how_to_install_it(textarea):
    """Enabled without the script: an explanation, not a broken editor."""
    textarea.unlink()

    with TestClient(app) as client:
        response = client.get("/textarea")
        assert response.status_code == 503
        assert "bin/fetch_editor.py" in response.text
        assert "TEXTAREA=true" in response.text

        assert client.get("/textarea/witty-editor.js").status_code == 404


def test_csp_lets_the_page_run(textarea):
    """Its inline script and same-origin editor script, and nothing else."""
    with TestClient(app) as client:
        csp = client.get("/textarea").headers["content-security-policy"]

    directives = dict(
        (part.split()[0], part.split()[1:]) for part in csp.split(";") if part.strip()
    )
    assert {"'self'", "'unsafe-inline'"} <= set(directives["script-src"])
    # The page's fetches go to its own origin; connect-src falls back to this.
    assert "'self'" in directives["default-src"]
    # The popover's inline logo and its learning-bite pictures.
    assert {"data:", "www.witty.works"} <= set(directives["img-src"])


def test_page_structure_for_assistive_technology():
    """What axe and a screen reader need from the page's own markup; the
    editor and its popover are checked where they are built."""
    assert '<html lang="en">' in PAGE
    assert PAGE.count("<main>") == 1

    # Every field has a visible label pointing at it.
    for field in re.findall(r"<(?:input|textarea|select)\b[^>]*>", PAGE):
        field_id = re.search(r'id="([^"]+)"', field).group(1)
        assert f'<label for="{field_id}">' in PAGE, field_id

    # Results are announced rather than only drawn.
    for region in ("status", "write-status"):
        assert f'<p id="{region}" role="status" aria-live="polite">' in PAGE

    # Strike-through and colour are spoken as words, new tabs are announced.
    script = page_script()
    assert 'hidden(op === "insert" ? "added: " : "removed: ")' in script
    assert 'hidden(" (opens in a new tab)")' in script


def test_page_explains_itself_and_where_to_get_a_key(textarea):
    """What a first-time visitor needs: what it is for, how the key is
    handled, and whom to ask for one."""
    with TestClient(app) as client:
        page = client.get("/textarea").text

    assert '<a href="https://witty.works">Witty Works</a>' in page
    assert "What you can use it for" in page
    assert '<a href="#get-a-key">Request one</a>' in page
    assert (
        '<a href="mailto:api@witty.works?subject=API%20key%20request">'
        "api@witty.works</a>"
    ) in page
    # The hints are tied to their fields for screen readers.
    for hint in ("api-key-help", "prompt-help"):
        assert f'aria-describedby="{hint}"' in page
        assert f'id="{hint}"' in page


def test_the_contact_is_the_deployments(textarea, monkeypatch):
    """A self-hosted page names its own contact, or none."""
    monkeypatch.setattr(context.settings, "textarea_contact", 'keys@example.org"><b>')
    with TestClient(app) as client:
        page = client.get("/textarea").text
    assert "api@witty.works" not in page
    assert "keys@example.org&quot;&gt;&lt;b&gt;" in page
    assert "<b>" not in page

    monkeypatch.setattr(context.settings, "textarea_contact", "")
    with TestClient(app) as client:
        page = client.get("/textarea").text
    assert "get-a-key" not in page
    assert "mailto:" not in page


def page_script() -> str:
    return PAGE.split("<script>")[1].split("</script>")[0]


def test_the_key_goes_only_into_x_key():
    """The key is typed into a password field and sent as a header, and the
    page itself keeps it nowhere else."""
    field = re.search(r'<input\s[^>]*id="api-key"[^>]*>', PAGE).group(0)
    assert 'type="password"' in field
    assert 'autocomplete="off"' in field
    assert "value=" not in field

    script = page_script()
    for storage in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert storage not in script

    # Read from the field for each request and passed on as the header; the
    # editor component gets it through setApiKey.
    assert '"x-key": apiKey.value' in script
    assert "editor.setApiKey(apiKey.value)" in script


def test_the_page_calls_routes_that_exist():
    """Every API path the page fetches is a POST route of this API."""
    called = set(re.findall(r'fetch\("(/[^"]+)"', page_script()))
    assert called, "the page fetches nothing"

    posts = {
        route.path for route in app.routes if "POST" in getattr(route, "methods", set())
    }
    assert called <= posts, called - posts


def load_fetch_editor():
    spec = importlib.util.spec_from_file_location(
        "fetch_editor", ROOT / "bin" / "fetch_editor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def tarball(files: dict[str, bytes]) -> bytes:
    """An npm package tarball: everything under package/."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    return buffer.getvalue()


def integrity(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def fake_registry(data: bytes):
    requested = []

    @contextmanager
    def opener(url, timeout):
        # Always bounded, so a stalled registry cannot hang a Docker build.
        assert timeout
        requested.append(url)
        yield io.BytesIO(data)

    opener.requested = requested
    return opener


def test_fetch_editor_installs_the_pinned_package(tmp_path):
    fetch_editor = load_fetch_editor()
    package = tarball(
        {
            "dist/witty-editor.js": b"editor",
            "LICENSE": b"MIT",
            "README.md": b"not installed",
        }
    )
    registry = fake_registry(package)

    fetch_editor.download(
        "@witty-works/editor", "2.0.0", integrity(package), tmp_path, registry
    )
    assert registry.requested == [
        "https://registry.npmjs.org/@witty-works/editor/-/editor-2.0.0.tgz"
    ]
    assert (tmp_path / "witty-editor.js").read_bytes() == b"editor"
    # The package's licence stands in for notices it does not ship yet.
    assert (tmp_path / "witty-editor.js.LICENSE.txt").read_bytes() == b"MIT"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "witty-editor.js",
        "witty-editor.js.LICENSE.txt",
    ]


def test_fetch_editor_prefers_the_bundled_notices(tmp_path):
    fetch_editor = load_fetch_editor()
    package = tarball(
        {
            "dist/witty-editor.js": b"editor",
            "dist/witty-editor.js.LICENSE.txt": b"all bundled notices",
            "LICENSE": b"MIT",
        }
    )

    fetch_editor.download(
        "@witty-works/editor",
        "2.0.1",
        integrity(package),
        tmp_path,
        fake_registry(package),
    )
    notices = tmp_path / "witty-editor.js.LICENSE.txt"
    assert notices.read_bytes() == b"all bundled notices"


def test_fetch_editor_refuses_anything_but_the_pin(tmp_path):
    fetch_editor = load_fetch_editor()
    package = tarball({"dist/witty-editor.js": b"editor", "LICENSE": b"MIT"})
    tampered = tarball({"dist/witty-editor.js": b"something else", "LICENSE": b"MIT"})

    with pytest.raises(fetch_editor.FetchError, match="does not match"):
        fetch_editor.download(
            "@witty-works/editor",
            "2.0.0",
            integrity(package),
            tmp_path,
            fake_registry(tampered),
        )
    assert not any(tmp_path.iterdir())

    # A package without the script is refused too, however it hashes.
    empty = tarball({"LICENSE": b"MIT"})
    with pytest.raises(fetch_editor.FetchError, match="dist/witty-editor.js"):
        fetch_editor.download(
            "@witty-works/editor",
            "2.0.0",
            integrity(empty),
            tmp_path,
            fake_registry(empty),
        )
    assert not any(tmp_path.iterdir())


def test_fetch_editor_is_pinned():
    """The script names an exact version and its sha512, not a range or tag."""
    fetch_editor = load_fetch_editor()

    assert re.fullmatch(r"\d+\.\d+\.\d+", fetch_editor.VERSION)
    assert fetch_editor.INTEGRITY.startswith("sha512-")


def audit_result(repository, path, ref, predicate="https://slsa.dev/provenance/v1"):
    """What `npm audit signatures --json --include-attestations` reports."""
    statement = {
        "predicate": {
            "buildDefinition": {
                "externalParameters": {
                    "workflow": {"repository": repository, "path": path, "ref": ref}
                },
                "resolvedDependencies": [{"digest": {"gitCommit": "abc123"}}],
            }
        }
    }
    payload = base64.b64encode(json.dumps(statement).encode()).decode()

    return {
        "invalid": [],
        "missing": [],
        "verified": [
            {
                "name": "@witty-works/editor",
                "version": "2.0.2",
                "attestationBundles": [
                    {
                        "predicateType": predicate,
                        "bundle": {"dsseEnvelope": {"payload": payload}},
                    }
                ],
            }
        ],
    }


def test_pin_accepts_only_our_publish_workflow():
    """Signed and attested is not enough: built by the browser-extension's
    publish workflow, from the version's own tag."""
    fetch_editor = load_fetch_editor()
    repository = "https://github.com/witty-works/browser-extension"
    workflow = ".github/workflows/publish-editor.yaml"

    def check(audit):
        return fetch_editor.check_provenance(audit, "@witty-works/editor", "2.0.2")

    assert check(audit_result(repository, workflow, "refs/tags/2.0.2")) == "abc123"

    for audit in (
        audit_result("https://github.com/someone/fork", workflow, "refs/tags/2.0.2"),
        audit_result(repository, ".github/workflows/other.yaml", "refs/tags/2.0.2"),
        audit_result(repository, workflow, "refs/heads/main"),
    ):
        with pytest.raises(fetch_editor.FetchError, match="was built by"):
            check(audit)

    # A publish attestation alone, no provenance.
    only_publish = audit_result(
        repository,
        workflow,
        "refs/tags/2.0.2",
        predicate="https://github.com/npm/attestation/tree/main/specs/publish/v0.1",
    )
    with pytest.raises(fetch_editor.FetchError, match="no verified provenance"):
        check(only_publish)

    failed = {**audit_result(repository, workflow, "refs/tags/2.0.2"), "invalid": [{}]}
    with pytest.raises(fetch_editor.FetchError, match="invalid or missing"):
        check(failed)


def test_pin_rewrites_only_the_pin():
    fetch_editor = load_fetch_editor()
    source = (ROOT / "bin" / "fetch_editor.py").read_text()
    integrity = "sha512-" + "A" * 86 + "=="

    rewritten = fetch_editor.rewrite_pin(source, "2.0.2", integrity)
    lines = [line for line in rewritten.splitlines() if line not in source.splitlines()]
    assert lines == [
        'VERSION = "2.0.2"',
        f'    "{integrity[:47]}"',
        f'    "{integrity[47:]}"',
    ]

    # And what it wrote reads back as that pin.
    pinned = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(rewritten).body
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", None) in ("VERSION", "INTEGRITY")
    }
    assert pinned == {"VERSION": "2.0.2", "INTEGRITY": integrity}


def test_script_is_revalidated_not_redownloaded(textarea):
    """no-cache so a new install is picked up, an ETag so an unchanged one
    costs a 304 rather than the whole script."""
    with TestClient(app) as client:
        response = client.get("/textarea/witty-editor.js")
        etag = response.headers["etag"]
        assert response.headers["cache-control"] == "no-cache"

        again = client.get("/textarea/witty-editor.js", headers={"If-None-Match": etag})
        assert again.status_code == 304
        assert again.content == b""

        # A reinstall changes the ETag, and the new script is sent.
        textarea.write_text("window.WittyEditor = {mount() {}, v: 2};")
        response = client.get(
            "/textarea/witty-editor.js", headers={"If-None-Match": etag}
        )
        assert response.status_code == 200
        assert response.headers["etag"] != etag


def test_page_limits_match_the_api(textarea):
    """The page refuses what /v1.0/write would, before sending it."""
    from app.models import WRITE_PROMPT_MAX_LENGTH, WRITE_TEXT_MAX_LENGTH

    with TestClient(app) as client:
        page = client.get("/textarea").text

    assert f'maxlength="{WRITE_PROMPT_MAX_LENGTH}"' in page
    assert f"const TEXT_MAX = {WRITE_TEXT_MAX_LENGTH};" in page
    # The editor splits long texts into requests the API checks whole.
    assert f"maxRequestLength: {context.settings.text_max_length}," in page
    assert "__" not in page.split("<script>")[1]


def test_a_prompt_run_is_one_at_a_time_and_keeps_the_editor_still():
    script = page_script()
    # Ctrl/Cmd+Enter submits past a disabled button, so the handler checks.
    assert "if (run.disabled || !prompt.value.trim()) return;" in script
    # Typing during a run would be overwritten by the answer.
    assert "editor.editor.setEditable(false);" in script
    # The draft is checked with the editor's own settings.
    assert "editor.getSettings().config" in script
    # The help text is added to the editor's own hint, not put in its place.
    assert 'describedBy: "editor-help"' in script
    assert "aria-describedby" not in script


def test_imprint_link_is_the_deployments(textarea, monkeypatch):
    """No imprint unless configured; a web address only."""
    with TestClient(app) as client:
        assert "Imprint" not in client.get("/textarea").text

        monkeypatch.setattr(
            context.settings,
            "textarea_imprint_url",
            "https://www.witty.works/impressum",
        )
        page = client.get("/textarea").text
        assert '<a href="https://www.witty.works/impressum">Imprint</a>' in page

        monkeypatch.setattr(
            context.settings, "textarea_imprint_url", "javascript:alert(1)"
        )
        page = client.get("/textarea").text
        assert "Imprint" not in page
        assert "javascript:" not in page


def test_ai_suggestions_are_off_until_ticked():
    """Each AI suggestion is an LLM request, so the editor starts without
    them; the page's own checkbox turns them on, kept in step with the
    editor's settings panel, and only for a key the server lets use the LLM."""
    script = page_script()

    assert "llmAlternatives: false" in script
    assert "editor.updateSettings({ llmAlternatives: aiSuggestions.checked })" in script
    assert "aiSuggestions.checked = next.llmAlternatives" in script
    # The server reports a refused LLM as forced off.
    assert 'fetch("/v2.0/auth"' in script
    assert 'setting?.status === "force" && setting.value === false' in script

    box = re.search(r'<input\s[^>]*id="ai-suggestions"[^>]*>', PAGE).group(0)
    assert 'type="checkbox"' in box
    assert "disabled" in box
