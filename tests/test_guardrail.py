"""The guardrail primitives and /v1.0/guardrail/*: guidance for the request,
a verdict and a reask for the response, and never an LLM call of their own."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.guidance import (
    BARE_TEXT_INSTRUCTION,
    BASE_GUIDANCE,
    guidance,
    merge_guidance,
)
from app.main import app
from app.models import Config, GermanGenderEndingType, LangWithAutoType
from tests.test_api import set_redis  # noqa: F401  (fixture)
from tests.test_llm_calls import answer, prompt_with


def test_guidance_has_base_text():
    assert guidance(Config()).startswith(BASE_GUIDANCE)


@pytest.mark.parametrize(
    "lang, german, french",
    [
        (None, True, True),
        (LangWithAutoType.AUTO, True, True),
        (LangWithAutoType.DE, True, False),
        (LangWithAutoType.deCH, True, False),
        (LangWithAutoType.FR, False, True),
        (LangWithAutoType.EN, False, False),
        (LangWithAutoType.enUS, False, False),
    ],
)
def test_guidance_lines_per_language(lang, german, french):
    text = guidance(Config(), lang)

    assert ("When writing German" in text) is german
    assert ("When writing French" in text) is french


def test_guidance_german_example():
    config = Config(german_gender_ending=GermanGenderEndingType.COLON)

    assert '"Lehrer:in"' in guidance(config)


def test_guidance_inklusivum_has_no_german_line():
    config = Config(german_gender_ending=GermanGenderEndingType.INKLUSIVUM)

    assert "When writing German" not in guidance(config)


def test_merge_appends_to_system_message():
    system = {"role": "system", "content": "Be brief."}
    user = {"role": "user", "content": "Hi"}
    messages = [system, user]

    merged = merge_guidance(messages, "Be kind.")

    assert merged == [{"role": "system", "content": "Be brief.\n\nBe kind."}, user]
    assert system == {"role": "system", "content": "Be brief."}
    assert messages == [system, user]


def test_merge_prepends_system_message():
    user = {"role": "user", "content": "Hi"}

    assert merge_guidance([user], "Be kind.") == [
        {"role": "system", "content": "Be kind."},
        user,
    ]


def test_merge_into_parts_system_message():
    system = {"role": "system", "content": [{"type": "text", "text": "Be brief."}]}

    merged = merge_guidance([system], "Be kind.")

    assert merged[0]["content"] == [
        {"type": "text", "text": "Be brief."},
        {"type": "text", "text": "Be kind."},
    ]
    assert system["content"] == [{"type": "text", "text": "Be brief."}]


def test_default_system_prompt_unchanged(monkeypatch):
    """/v1.0/rephrase and the AI suggestions keep the prompt they had."""
    prompt, calls = prompt_with(monkeypatch, answer("ok"))

    asyncio.run(prompt.handle("hi"))

    system = calls[0]["messages"][0]["content"]
    assert system == BASE_GUIDANCE + "\n\n" + BARE_TEXT_INSTRUCTION
    assert "Do not make biased assumptions." in system
    assert '"Here is .."' in system


AUTH = {"X-TESTING-AUTH": "default@gmail.com"}


@pytest.fixture
def llm_calls(monkeypatch):
    """What the endpoint sent to a model: nothing, if it keeps its promise."""
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        return answer("unexpected")

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    return calls


def post(path, body, headers=AUTH):
    with TestClient(app) as client:
        return client.post(path, json=body, headers=headers)


def test_input_adds_guidance(set_redis, llm_calls):  # noqa: F811
    user = {"role": "user", "content": "Write a job ad."}

    response = post("/v1.0/guardrail/input", {"messages": [user]})

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "modify"
    assert body["messages"][0] == {"role": "system", "content": body["guidance"]}
    assert body["messages"][1] == user
    assert body["guidance"].startswith(BASE_GUIDANCE)


def test_input_respects_config(set_redis, llm_calls):  # noqa: F811
    response = post(
        "/v1.0/guardrail/input",
        {
            "messages": [{"role": "user", "content": "Schreib ein Inserat."}],
            "lang": "de",
            "config": {"german_gender_ending": ":in"},
        },
    )

    assert response.status_code == 200
    assert '"Lehrer:in"' in response.json()["guidance"]
    assert "When writing French" not in response.json()["guidance"]


def test_input_passes_other_messages_through(set_redis, llm_calls):  # noqa: F811
    tool_turn = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
        ],
    }
    messages = [{"role": "user", "content": "Look it up."}, tool_turn]

    response = post("/v1.0/guardrail/input", {"messages": messages})

    assert response.status_code == 200
    assert response.json()["messages"][1:] == messages


def test_input_requires_a_user(set_redis, llm_calls):  # noqa: F811
    response = post(
        "/v1.0/guardrail/input",
        {"messages": [{"role": "user", "content": "Hi"}]},
        headers={},
    )

    assert response.status_code == 401


def test_input_makes_no_llm_call(set_redis, llm_calls):  # noqa: F811
    response = post(
        "/v1.0/guardrail/input", {"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 200
    assert llm_calls == []


FLAGGED = "The chairman called the policemen."


def check_output(body, headers=AUTH):
    return post("/v1.0/guardrail/output", body, headers)


def test_output_fail_with_reask(set_redis, llm_calls):  # noqa: F811
    response = check_output({"response": FLAGGED, "lang": "en"})

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "fail"
    assert body["findings"]
    assert body["language"] == "en"
    assert body["reask"]["role"] == "user"
    assert FLAGGED in body["reask"]["content"]


def test_output_pass(set_redis, llm_calls):  # noqa: F811
    response = check_output({"response": "We support inclusion, diversity and equity."})

    assert response.status_code == 200
    assert response.json()["verdict"] == "pass"
    assert "reask" not in response.json()


def test_output_threshold(set_redis, llm_calls):  # noqa: F811
    findings = check_output({"response": FLAGGED, "lang": "en"}).json()["findings"]
    actionable = len([f for f in findings if f.get("alternatives")])

    at = check_output({"response": FLAGGED, "lang": "en", "threshold": actionable})
    above = check_output(
        {"response": FLAGGED, "lang": "en", "threshold": actionable + 1}
    )

    assert at.json()["verdict"] == "fail"
    assert above.json()["verdict"] == "pass"
    assert "reask" not in above.json()


def test_output_rejects_threshold_below_one(set_redis, llm_calls):  # noqa: F811
    response = check_output({"response": FLAGGED, "threshold": 0})

    assert response.status_code == 422


def test_output_long_response_is_checked_in_part(set_redis, llm_calls):  # noqa: F811
    response = check_output({"response": "The chairman called. " * 100, "lang": "en"})

    assert response.status_code == 200
    assert response.json()["limit_reached"] is True


def test_output_empty_response_passes(set_redis, llm_calls):  # noqa: F811
    response = check_output({"response": ""})

    assert response.status_code == 200
    assert response.json()["verdict"] == "pass"
    assert response.json()["findings"] == []


def test_output_requires_a_user(set_redis, llm_calls):  # noqa: F811
    assert check_output({"response": FLAGGED}, headers={}).status_code == 401


def test_output_makes_no_llm_call(set_redis, llm_calls):  # noqa: F811
    response = check_output({"response": FLAGGED, "lang": "en"})

    assert response.status_code == 200
    assert llm_calls == []


def test_output_reports_an_unknown_language_as_null(set_redis, llm_calls):  # noqa: F811
    """The spec's `language: null`, not a missing key."""
    body = check_output({"response": ""}).json()

    assert "language" in body
    assert body["language"] is None
