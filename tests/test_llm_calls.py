"""How LLM calls are bounded and how their failures reach a client."""

import asyncio

import litellm
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prompt import LlmCutOff, LlmUnavailable, Prompt, llm_error
from app.settings import Settings
from app.models import LlmAccessType
from tests.test_api import llm_access, set_redis  # noqa: F401  (fixtures)


def answer(content, finish_reason="stop"):
    message = type("Message", (), {"content": content})
    choice = type("Choice", (), {"message": message, "finish_reason": finish_reason})
    return type("Response", (), {"choices": [choice]})


def prompt_with(monkeypatch, reply, **settings):
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    prompt = Prompt(Settings(llm_model="openai/test", **settings))

    return prompt, calls


def test_a_call_is_bounded_by_the_settings(monkeypatch):
    prompt, calls = prompt_with(
        monkeypatch, answer("ok"), llm_max_tokens=1234, llm_timeout=7.0
    )

    assert asyncio.run(prompt.handle("hi")) == "ok"
    assert calls[0]["max_tokens"] == 1234
    assert calls[0]["timeout"] == 7.0
    assert calls[0]["num_retries"] == 0


def test_a_cut_off_answer_is_refused(monkeypatch):
    """A reasoning model that ran out of tokens returns its unfinished
    reasoning, or a truncated JSON object; neither may be used."""
    prompt, _ = prompt_with(monkeypatch, answer("Let me think", "length"))

    with pytest.raises(LlmCutOff, match="LLM_MAX_TOKENS"):
        asyncio.run(prompt.handle("hi"))


def test_provider_trouble_is_unavailable(monkeypatch):
    busy = litellm.RateLimitError("slow down", llm_provider="openai", model="test")
    prompt, _ = prompt_with(monkeypatch, busy)

    with pytest.raises(LlmUnavailable):
        asyncio.run(prompt.handle("hi"))


def test_calls_beyond_the_limit_wait_for_a_slot(monkeypatch):
    running, peak = 0, 0

    async def acompletion(**kwargs):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return answer("ok")

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    prompt = Prompt(Settings(llm_model="openai/test", llm_max_concurrency=2))

    async def five():
        return await asyncio.gather(*(prompt.handle("hi") for _ in range(5)))

    assert asyncio.run(five()) == ["ok"] * 5
    assert peak == 2


def test_no_free_slot_in_time_is_unavailable(monkeypatch):
    async def acompletion(**kwargs):
        await asyncio.sleep(1)
        return answer("ok")

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    prompt = Prompt(
        Settings(llm_model="openai/test", llm_max_concurrency=1, llm_timeout=0.05)
    )

    async def two():
        return await asyncio.gather(
            prompt.handle("hi"), prompt.handle("hi"), return_exceptions=True
        )

    results = asyncio.run(two())
    assert any(isinstance(result, LlmUnavailable) for result in results)


def test_parse_json_keeps_umlauts():
    """A single escaped character used to garble every raw umlaut."""
    prompt = Prompt(Settings())

    assert prompt.parse_json('{"a": "Lehrkr\\u00e4fte für Schüler"}') == {
        "a": "Lehrkräfte für Schüler"
    }


@pytest.mark.parametrize(
    "error,status",
    [(LlmUnavailable("busy"), 503), (LlmCutOff("cut"), 502), (ValueError("x"), 500)],
)
def test_each_failure_has_its_status(error, status):
    code, headers, message = llm_error(error, "/test")

    assert code == status
    assert ("Retry-After" in headers) == (status == 503)
    assert "x" != message  # nothing internal in the message


def test_the_rephrase_route_answers_503_when_the_llm_is_busy(
    llm_access, set_redis, monkeypatch  # noqa: F811
):
    # test@gmail.com's organisation forces llm_alternatives on.
    llm_access(LlmAccessType.USERS)

    async def busy(*args, **kwargs):
        raise LlmUnavailable("rate limited")

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.context.prompt, "handle", busy)
        response = client.post(
            "/v1.0/rephrase",
            json={
                "sentence": "Hey guys, the chairman will be late.",
                "text": "guys",
                "start": 4,
                "lang": "en",
                "alternatives": [{"text": "everyone"}],
            },
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "10"
