"""bin/llm_check.py: testing the configured model on known cases."""

import pathlib

from bin.llm_check import Case, load_cases, main, run

CHAIR = Case(
    name="chair",
    body={
        "sentence": "The chairman decides.",
        "text": "chairman",
        "start": 4,
        "alternatives": [{"text": "chair"}],
        "lang": "en",
    },
    forbidden=["chairman"],
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Answers every rephrase request with `results` and `model`."""

    def __init__(self, results, model="served"):
        self.results = results
        self.model = model
        self.headers = []

    def post(self, path, json, headers):
        self.headers.append(headers)
        return FakeResponse(200, {"results": self.results, "model": self.model})


def no_sleep(seconds):
    pass


def test_a_passing_case_passes():
    client = FakeClient({"chair": "The chair decides."})
    [result] = run([CHAIR], 1, client, {}, pause=0, sleep=no_sleep)
    assert result.passed and result.served_model == "served"


def test_a_dropped_suggestion_fails_the_case():
    [result] = run([CHAIR], 1, FakeClient({}), {}, pause=0, sleep=no_sleep)
    assert not result.passed
    assert "chair" in result.reason


def test_a_forbidden_string_fails_the_case():
    client = FakeClient({"chair": "The chairman decides."})
    [result] = run([CHAIR], 1, client, {}, pause=0, sleep=no_sleep)
    assert not result.passed
    assert "chairman" in result.reason


def test_calls_are_paced():
    waits = []
    client = FakeClient({"chair": "The chair decides."})
    run([CHAIR, CHAIR], 2, client, {}, pause=1.1, sleep=waits.append)
    # Four calls, a pause before each but the first.
    assert len(waits) == 3 and all(wait >= 1.1 for wait in waits)


def test_the_stored_and_new_cases_load():
    cases = load_cases(
        [pathlib.Path("tests/test_rephrase"), pathlib.Path("tests/llm_check")]
    )
    names = {case.name for case in cases}
    assert {"test_english_past_tense", "chair_not_chairman"} <= names
    assert next(c for c in cases if c.name == "chair_not_chairman").forbidden == [
        "chairman"
    ]


def run_main(monkeypatch, capsys, client, *args, expected=""):
    monkeypatch.setenv("LLM_CHECK_KEY", "secret-key-value")
    monkeypatch.setattr(
        "bin.llm_check.context_settings_expected_model", lambda: expected
    )
    code = main(
        ["--api-key-env", "LLM_CHECK_KEY", "--cases", "tests/llm_check", *args],
        client_factory=lambda: client,
        sleep=no_sleep,
    )
    return code, capsys.readouterr().out


def test_an_expected_model_mismatch_fails_the_run(monkeypatch, capsys):
    client = FakeClient(
        {
            "chair": "The chair decides.",
            "all": "When I am with all, I feel like one of the guys",
            "Les expert·es": "Les expert·es rapides sont intelligent·es.",
            "closely examine": "We closely examined if this works",
        },
        model="other",
    )
    code, out = run_main(monkeypatch, capsys, client, expected="expected")
    assert code == 1
    assert "other" in out


def test_the_key_is_sent_but_not_printed(monkeypatch, capsys):
    client = FakeClient({})
    code, out = run_main(monkeypatch, capsys, client)
    assert code == 1
    assert client.headers[0]["x-key"] == "secret-key-value"
    assert "secret-key-value" not in out
