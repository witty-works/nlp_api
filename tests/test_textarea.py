"""The /textarea page as this API hosts it.

The editor component the page loads is tested where it is built (the
browser-extension repository, packages/editor); these cover what is decided
here: that the page is opt-in, how it sits behind the key gate, what it serves
without its script, and the page's own contract with the API.
"""

import hashlib
import importlib.util
import io
import re
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


def page_script() -> str:
    return PAGE.split("<script>")[1].split("</script>")[0]


def test_the_key_goes_only_into_x_key():
    """The key is typed into a password field and sent as a header, and the
    page itself keeps it nowhere else."""
    field = re.search(r'<input id="api-key"[^>]*>', PAGE).group(0)
    assert 'type="password"' in field
    assert 'autocomplete="off"' in field
    assert "value=" not in field

    script = page_script()
    for storage in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert storage not in script

    # Read from the field for each request and passed on as the header; the
    # editor component gets it through setApiKey.
    assert '"x-key": apiKey.value' in script
    assert "editor.setApiKey(event.target.value)" in script


def test_the_page_calls_routes_that_exist():
    """Every API path the page fetches is a POST route of this API."""
    called = set(re.findall(r'fetch\("(/[^"]+)"', page_script()))
    assert called, "the page fetches nothing"

    posts = {
        route.path
        for route in app.routes
        if "POST" in getattr(route, "methods", set())
    }
    assert called <= posts, called - posts


def load_fetch_editor():
    spec = importlib.util.spec_from_file_location(
        "fetch_editor", ROOT / "bin" / "fetch_editor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def fake_opener(files: dict[str, bytes]):
    @contextmanager
    def opener(url):
        yield io.BytesIO(files[url.rsplit("/", 1)[1]])

    return opener


def test_fetch_editor_installs_only_what_was_pinned(tmp_path):
    fetch_editor = load_fetch_editor()
    served = {"witty-editor.js": b"editor", "witty-editor.js.LICENSE.txt": b"notices"}
    pins = {name: hashlib.sha256(data).hexdigest() for name, data in served.items()}

    fetch_editor.download("v1", pins, tmp_path, fake_opener(served))
    assert (tmp_path / "witty-editor.js").read_bytes() == b"editor"
    assert (tmp_path / "witty-editor.js.LICENSE.txt").read_bytes() == b"notices"

    # One file that does not match its pin, and nothing is written at all.
    target = tmp_path / "second"
    tampered = {**served, "witty-editor.js.LICENSE.txt": b"something else"}
    with pytest.raises(fetch_editor.FetchError, match="does not match"):
        fetch_editor.download("v1", pins, target, fake_opener(tampered))
    assert not target.exists()


def test_fetch_editor_refuses_without_a_pin(tmp_path):
    fetch_editor = load_fetch_editor()

    with pytest.raises(fetch_editor.FetchError, match="--build"):
        fetch_editor.download("", fetch_editor.FILES, tmp_path, fake_opener({}))
