"""bin/check_translations.py: translation files checked with config/witty.json.

The API is a local stand-in here, so the reading, the requests and the
report are tested without a running API.
"""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.models import Config
from bin import check_translations as ct

FLAGGED = {
    "text": "Nutzer",
    "category": "gender-orientation",
    "subcategory": "function",
    "label": "Generisches Maskulinum",
    "gravity": 2.0,
    "alternatives": [{"text": "Nutzende"}],
}


class StandIn(BaseHTTPRequestHandler):
    requests: list = []
    redirect = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append({"body": body, "key": self.headers.get("x-key")})
        if type(self).redirect:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.end_headers()
            return
        results = [FLAGGED] if "Nutzer" in body["text"] else []
        # A confirmation (gravity null, no alternatives) is no finding.
        results.append({"text": "Team", "gravity": None, "alternatives": []})
        payload = json.dumps({"results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def api():
    StandIn.requests, StandIn.redirect = [], False
    server = HTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield StandIn, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def lang(tmp_path):
    (tmp_path / "de").mkdir()
    (tmp_path / "de" / "messages.json").write_text(
        json.dumps(
            {
                "welcome": {"message": "Willkommen im Team"},
                "user": {"message": "Kein Nutzer gefunden"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "fr.json").write_text(
        json.dumps(
            {"Hello!": "Bonjour :name !", "example_separator": "p. ex. expert·es"}
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_the_witty_config_is_a_check_config_the_api_accepts():
    config = json.loads(ct.WITTY_CONFIG.read_text(encoding="utf-8"))

    assert set(config) <= set(Config.model_fields), set(config) - set(
        Config.model_fields
    )
    validated = Config.model_validate(config)
    assert validated.model_dump(include=set(config), mode="json") == config


def test_messages_json_and_nested_json_are_read():
    assert list(
        ct.flatten({"a": {"message": "One"}, "b": {"c": "Two", "d": ["Three"]}})
    ) == [
        ("a", "One"),
        ("b.c", "Two"),
        ("b.d.0", "Three"),
    ]


def test_a_po_catalogue_gives_translations_and_singular_plurals(tmp_path):
    po = tmp_path / "messages.po"
    po.write_text(
        'msgid ""\nmsgstr "Content-Type: text/plain\\n"\n\n'
        '#: app/x.py\nmsgid "Hello"\nmsgstr "Hallo"\n\n'
        'msgid "Untranslated"\nmsgstr ""\n\n'
        'msgid "One user"\nmsgid_plural "%d users"\nmsgstr[0] "Ein Nutzer"\nmsgstr[1] "%d Nutzer"\n\n'
        'msgid "Long"\nmsgstr ""\n"zwei "\n"Zeilen"\n',
        encoding="utf-8",
    )

    assert list(ct.read_po(po)) == [
        ("Hello", "Hallo"),
        ("Untranslated", "Untranslated"),
        ("One user", "Ein Nutzer"),
        ("Long", "zwei Zeilen"),
    ]


@pytest.mark.skipif(shutil.which("php") is None, reason="needs php")
def test_a_laravel_file_is_read(tmp_path):
    php = tmp_path / "teams.php"
    php.write_text(
        "<?php return ['owner' => 'Eigentümer*in', 'nested' => ['a' => 'B']];",
        encoding="utf-8",
    )

    assert list(ct.read_php(php)) == [("owner", "Eigentümer*in"), ("nested.a", "B")]


@pytest.mark.parametrize(
    "path, lang",
    [
        ("resources/lang/de/teams.php", "de"),
        ("resources/lang/fr.json", "fr"),
        ("_locales/en/messages.json", "en"),
        ("locales/de_CH/LC_MESSAGES/messages.po", "de"),
        ("locales/messages.po", None),
    ],
)
def test_the_language_comes_from_the_path(path, lang):
    assert ct.language_of(Path(path), None) == lang


def test_placeholders_and_markup_are_left_out():
    assert ct.clean(
        "Hallo <strong>:name</strong>, du hast {count} Nachrichten (%1$s)."
    ) == ("Hallo , du hast Nachrichten ().")


@pytest.mark.parametrize(
    "api, allowed",
    [
        ("https://api.example.org", True),
        ("http://127.0.0.1:8000", True),
        ("http://localhost:8000", True),
        ("http://api.example.org", False),
    ],
)
def test_a_key_goes_over_https_or_to_this_machine_only(api, allowed):
    assert ct.may_send_key(api) is allowed


def test_findings_are_reported_by_file_and_key(api, lang, capsys):
    stand_in, url = api

    status = ct.main(
        [str(lang), "--api", url, "--format", "json", "--exclude-key", "^example_"]
    )

    report = json.loads(capsys.readouterr().out)
    assert status == 1
    assert [
        (Path(r["file"]).name, r["key"], [f["text"] for f in r["findings"]])
        for r in report
    ] == [("messages.json", "user", ["Nutzer"])]
    sent = {r["body"]["text"]: r["body"] for r in stand_in.requests}
    assert set(sent) == {"Willkommen im Team", "Kein Nutzer gefunden", "Bonjour !"}
    assert sent["Kein Nutzer gefunden"]["lang"] == "de"
    assert sent["Kein Nutzer gefunden"]["config"] == json.loads(
        ct.WITTY_CONFIG.read_text()
    )


def test_no_findings_is_success(api, tmp_path):
    stand_in, url = api
    (tmp_path / "en.json").write_text(
        json.dumps({"a": "Welcome to the team"}), encoding="utf-8"
    )

    assert ct.main([str(tmp_path), "--api", url]) == 0


def test_a_rerun_skips_what_the_cache_holds_for_the_same_config(api, lang, tmp_path):
    stand_in, url = api
    cache = tmp_path / "cache.jsonl"
    args = [str(lang), "--api", url, "--cache", str(cache)]

    ct.main(args)
    first = len(stand_in.requests)
    assert ct.main(args) == 1
    assert len(stand_in.requests) == first

    other = tmp_path / "other.json"
    other.write_text(json.dumps({"german_gender_ending": ":in"}), encoding="utf-8")
    ct.main(args + ["--config", str(other)])
    assert len(stand_in.requests) == 2 * first


def test_a_redirect_is_not_followed(api, lang, monkeypatch):
    stand_in, url = api
    stand_in.redirect = True
    monkeypatch.setenv("WITTY_API_KEY", "secret-key")

    assert ct.main([str(lang), "--api", url]) == 2
    # Each string was sent once, to the stand-in only.
    assert {r["key"] for r in stand_in.requests} == {"secret-key"}
    assert len(stand_in.requests) == 4


def test_a_key_is_not_sent_over_plain_http_to_another_host(lang, monkeypatch):
    monkeypatch.setenv("WITTY_API_KEY", "secret-key")

    assert ct.main([str(lang), "--api", "http://api.example.org"]) == 2


def test_an_unreadable_file_fails_the_run(api, lang):
    stand_in, url = api
    (lang / "de" / "broken.json").write_text("{not json", encoding="utf-8")

    assert ct.main([str(lang), "--api", url]) == 2


def test_a_file_in_no_language_is_skipped_without_failing(api, tmp_path):
    stand_in, url = api
    (tmp_path / "en.json").write_text(
        json.dumps({"a": "Welcome to the team"}), encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")

    assert ct.main([str(tmp_path), "--api", url]) == 0


def test_a_dropped_connection_is_a_failed_request(lang, monkeypatch):
    def reset(*args, **kwargs):
        raise ConnectionResetError("reset by peer")

    monkeypatch.setattr(ct.OPENER, "open", reset)

    assert ct.main([str(lang), "--api", "http://127.0.0.1:9"]) == 2


def test_a_corrupt_cache_line_is_ignored(api, lang, tmp_path):
    stand_in, url = api
    cache = tmp_path / "cache.jsonl"
    cache.write_text("{half a line\n", encoding="utf-8")

    assert ct.main([str(lang), "--api", url, "--cache", str(cache)]) == 1


@pytest.mark.skipif(shutil.which("php") is None, reason="needs php")
def test_a_file_named_like_an_option_is_read(tmp_path):
    php = tmp_path / "-v.php"
    php.write_text("<?php return ['a' => 'B'];", encoding="utf-8")

    assert list(ct.read_php(php)) == [("a", "B")]
