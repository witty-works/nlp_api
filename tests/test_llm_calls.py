"""How LLM calls are bounded and how their failures reach a client."""

import asyncio

import litellm
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prompt import (
    LlmAnswer,
    LlmCutOff,
    LlmTextRefused,
    LlmUnavailable,
    Prompt,
    llm_error,
)
from app.settings import Settings
from app.models import LlmAccessType
from tests.test_api import llm_access, set_redis  # noqa: F401  (fixtures)


def answer(content, finish_reason="stop", model="test"):
    message = type("Message", (), {"content": content})
    choice = type("Choice", (), {"message": message, "finish_reason": finish_reason})
    return type("Response", (), {"choices": [choice], "model": model})


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


def test_extra_body_reaches_the_provider_only_when_set(monkeypatch):
    no_thinking = {"chat_template_kwargs": {"enable_thinking": False}}
    prompt, calls = prompt_with(monkeypatch, answer("ok"), llm_extra_body=no_thinking)
    asyncio.run(prompt.handle("hi"))
    assert calls[0]["extra_body"] == no_thinking

    prompt, calls = prompt_with(monkeypatch, answer("ok"))
    asyncio.run(prompt.handle("hi"))
    assert "extra_body" not in calls[0]


def test_extra_body_is_read_as_json_from_the_environment(monkeypatch):
    monkeypatch.setenv(
        "LLM_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": false}}'
    )
    assert Settings().llm_extra_body == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_a_bedrock_call_passes_no_aws_keys_of_its_own(monkeypatch):
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        return answer("ok")

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    prompt = Prompt(Settings(llm_model="bedrock/anthropic.claude-test"))
    asyncio.run(prompt.handle("hi"))
    assert "aws_access_key_id" not in calls[0]
    assert "aws_secret_access_key" not in calls[0]
    assert calls[0]["api_key"] is None


def test_bedrock_reaches_litellms_aws_credential_lookup(monkeypatch):
    """Not prompt_with: this goes through the real litellm.acompletion, up to
    where LiteLLM resolves the AWS credentials itself."""
    seen = {}

    def get_credentials(self, *args, **kwargs):
        seen.update(kwargs)
        seen["called"] = True
        raise RuntimeError("stop before the network")

    monkeypatch.setattr(
        "litellm.llms.bedrock.base_aws_llm.BaseAWSLLM.get_credentials",
        get_credentials,
    )
    prompt = Prompt(
        Settings(
            llm_model="bedrock/anthropic.claude-test", aws_region_name="eu-central-1"
        )
    )
    with pytest.raises(Exception):
        asyncio.run(prompt.handle("hi"))
    assert seen.get("called")
    assert seen.get("aws_access_key_id") is None


def test_the_task_reaches_the_call_params(monkeypatch):
    no_thinking = {"chat_template_kwargs": {"enable_thinking": False}}
    prompt, calls = prompt_with(
        monkeypatch, answer("ok"), llm_task_extra_body={"rephrase": no_thinking}
    )
    asyncio.run(prompt.handle("hi", task="rephrase"))
    asyncio.run(prompt.handle("hi", task="write"))
    assert calls[0]["extra_body"] == no_thinking
    assert "extra_body" not in calls[1]


def test_the_served_model_is_recorded(monkeypatch):
    prompt, _ = prompt_with(monkeypatch, answer("ok", model="served-model"))
    assert asyncio.run(prompt.answer("hi")).served_model == "served-model"
    assert prompt.last_served_model == "served-model"


def test_a_mismatch_warns_by_default(monkeypatch, caplog):
    prompt, _ = prompt_with(
        monkeypatch, answer("ok", model="other"), llm_expected_model="expected"
    )
    with caplog.at_level("WARNING", "nlp_api"):
        assert asyncio.run(prompt.handle("hi")) == "ok"
    assert "LLM answered with other, expected expected" in caplog.text
    assert prompt.last_model_matched is False


def test_a_match_is_recorded(monkeypatch):
    prompt, _ = prompt_with(
        monkeypatch, answer("ok", model="expected"), llm_expected_model="expected"
    )
    asyncio.run(prompt.handle("hi"))
    assert prompt.last_model_matched is True


def test_a_mismatch_is_refused_when_configured(monkeypatch):
    prompt, _ = prompt_with(
        monkeypatch,
        answer("ok", model="other"),
        llm_expected_model="expected",
        llm_model_mismatch="refuse",
    )
    with pytest.raises(LlmUnavailable):
        asyncio.run(prompt.handle("hi"))


def test_a_refused_mismatch_asks_clients_to_wait_longer(monkeypatch):
    """A mismatch lasts until the deployment changes, so clients are not told
    to come back in seconds and spend a paid call each time."""
    prompt, _ = prompt_with(
        monkeypatch,
        answer("ok", model="other"),
        llm_expected_model="expected",
        llm_model_mismatch="refuse",
    )
    with pytest.raises(LlmUnavailable) as refused:
        asyncio.run(prompt.handle("hi"))
    assert refused.value.retry_after == 300


def test_unknown_served_model_counts_as_mismatch(monkeypatch, caplog):
    prompt, _ = prompt_with(
        monkeypatch,
        answer("ok", model=None),
        llm_expected_model="expected",
        llm_model_mismatch="refuse",
    )
    with caplog.at_level("WARNING", "nlp_api"), pytest.raises(LlmUnavailable):
        asyncio.run(prompt.handle("hi"))
    assert "LLM answered with unknown" in caplog.text


def test_no_expected_model_means_no_comparison(monkeypatch, caplog):
    prompt, _ = prompt_with(monkeypatch, answer("ok", model="anything"))
    with caplog.at_level("WARNING", "nlp_api"):
        asyncio.run(prompt.handle("hi"))
    assert prompt.last_model_matched is None
    assert "expected" not in caplog.text


def test_a_cut_off_answer_still_records_its_model(monkeypatch):
    """An answer cut off at LLM_MAX_TOKENS was still served by some model:
    it is counted and compared like any other."""
    prompt, _ = prompt_with(
        monkeypatch,
        answer("Let me think", "length", model="other"),
        llm_expected_model="expected",
    )
    with pytest.raises(LlmCutOff):
        asyncio.run(prompt.handle("hi"))
    assert prompt.last_served_model == "other"
    assert prompt.last_model_matched is False


def test_a_long_served_model_name_is_capped(monkeypatch):
    """The name comes from the provider; it is stored and counted capped."""
    prompt, _ = prompt_with(monkeypatch, answer("ok", model="m" * 1000))
    asyncio.run(prompt.handle("hi"))
    assert len(prompt.last_served_model) <= 200


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


# The body a LiteLLM proxy sends when one of its guardrails refuses a request
# before it reaches the model (here the BFH inference server's, 2026-11-20).
GUARDRAIL_BODY = {
    "message": "Content blocked: AHV number pattern detected",
    "type": "invalid_request_error",
    "param": None,
    "code": "400",
    "provider_specific_fields": {
        "error": "Content blocked: AHV number pattern detected",
        "pattern": "AHV number",
        "guardrail_name": "Pattern Matching",
        "guardrail_mode": "pre_call",
    },
}


def test_a_gateway_guardrail_refusal_is_refused_with_its_reason(monkeypatch):
    blocked = litellm.BadRequestError(
        "OpenAIException - Content blocked: AHV number pattern detected",
        model="test",
        llm_provider="openai",
        body=GUARDRAIL_BODY,
    )
    prompt, _ = prompt_with(monkeypatch, blocked)

    with pytest.raises(LlmTextRefused) as refused:
        asyncio.run(prompt.handle("hi"))

    assert refused.value.reason == "Content blocked: AHV number pattern detected"


def test_a_content_policy_refusal_is_refused(monkeypatch):
    blocked = litellm.ContentPolicyViolationError(
        "rejected by the safety system", model="test", llm_provider="openai"
    )
    prompt, _ = prompt_with(monkeypatch, blocked)

    with pytest.raises(LlmTextRefused) as refused:
        asyncio.run(prompt.handle("hi"))

    assert refused.value.reason is None


def test_any_other_bad_request_stays_an_error(monkeypatch):
    """A wrong model name or parameter is the deployment's fault, not the
    text's, and must not read as a refusal."""
    wrong = litellm.BadRequestError(
        "model not found", model="test", llm_provider="openai", body={"message": "x"}
    )
    prompt, _ = prompt_with(monkeypatch, wrong)

    with pytest.raises(litellm.BadRequestError):
        asyncio.run(prompt.handle("hi"))


def test_a_refusal_passes_on_the_providers_reason():
    code, headers, message = llm_error(
        LlmTextRefused("Content blocked: AHV number pattern detected"), "/test"
    )

    assert code == 422
    assert headers == {}
    assert message == "Content blocked: AHV number pattern detected"


def test_the_deployments_refusal_message_replaces_the_reason(monkeypatch):
    """LLM_REFUSED_MESSAGE is the deployment's own explanation of what its
    provider refuses; Witty has none of its own."""
    blocked = litellm.BadRequestError(
        "blocked", model="test", llm_provider="openai", body=GUARDRAIL_BODY
    )
    prompt, _ = prompt_with(
        monkeypatch, blocked, llm_refused_message="Remove personal identifiers."
    )

    with pytest.raises(LlmTextRefused) as refused:
        asyncio.run(prompt.handle("hi"))

    assert llm_error(refused.value, "/test")[2] == "Remove personal identifiers."


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


def test_calls_beyond_the_minute_budget_are_refused(monkeypatch):
    """LLM_MAX_REQUESTS_PER_MINUTE: shared through Redis, so two workers (two
    Prompt instances) spend one budget; past it, a 503 until the next minute,
    and the provider is not called."""
    import fakeredis

    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        return answer("ok")

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    monkeypatch.setattr("app.prompt.time.time", lambda: 1_000_040.0)  # 20 s in
    db = fakeredis.FakeStrictRedis()
    settings = Settings(llm_model="openai/test", llm_max_requests_per_minute=3)
    workers = [Prompt(settings, db), Prompt(settings, db)]

    for i in range(3):
        assert asyncio.run(workers[i % 2].handle("hi")) == "ok"
    over_budget = workers[1].handle("hi")
    with pytest.raises(LlmUnavailable) as refused:
        asyncio.run(over_budget)
    assert len(calls) == 3
    assert refused.value.retry_after == 40
    assert llm_error(refused.value, "/test")[1] == {"Retry-After": "40"}

    # The next minute has its own budget.
    monkeypatch.setattr("app.prompt.time.time", lambda: 1_000_100.0)
    assert asyncio.run(workers[0].handle("hi")) == "ok"


def test_no_minute_budget_without_the_setting_or_redis(monkeypatch):
    import fakeredis

    prompt, calls = prompt_with(monkeypatch, answer("ok"))
    prompt.redis_db = fakeredis.FakeStrictRedis()
    for _ in range(5):
        asyncio.run(prompt.handle("hi"))

    limited, _ = prompt_with(monkeypatch, answer("ok"), llm_max_requests_per_minute=1)
    for _ in range(3):
        asyncio.run(limited.handle("hi"))  # no Redis given: not limited


def test_parse_json_keeps_umlauts():
    """A single escaped character used to garble every raw umlaut."""
    prompt = Prompt(Settings())

    assert prompt.parse_json('{"a": "Lehrkr\\u00e4fte für Schüler"}') == {
        "a": "Lehrkräfte für Schüler"
    }


@pytest.mark.parametrize(
    "error,status",
    [
        (LlmUnavailable("busy"), 503),
        (LlmCutOff("cut"), 502),
        (LlmTextRefused(None), 422),
        (ValueError("x"), 500),
    ],
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
        monkeypatch.setattr(app.state.context.prompt, "answer", busy)
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


def test_the_rephrase_route_answers_422_when_the_provider_refuses(
    llm_access, set_redis, monkeypatch  # noqa: F811
):
    llm_access(LlmAccessType.USERS)

    async def refused(*args, **kwargs):
        raise LlmTextRefused("Content blocked: AHV number pattern detected")

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.context.prompt, "answer", refused)
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

    assert response.status_code == 422
    assert "AHV number" in response.json()["detail"][0]["msg"]


def test_a_refusal_is_logged_without_the_providers_reason(monkeypatch, caplog):
    """A guardrail may quote what it matched, which is the user's text; the
    log gets only the guardrail's name (AGENTS.md, 1.1)."""
    body = {
        "message": "Blocked: found 756.1234.5678.97",
        "provider_specific_fields": {
            "error": "Blocked: found 756.1234.5678.97",
            "guardrail_name": "Pattern Matching",
        },
    }
    blocked = litellm.BadRequestError(
        "blocked", model="test", llm_provider="openai", body=body
    )
    prompt, _ = prompt_with(monkeypatch, blocked)

    with pytest.raises(LlmTextRefused) as refused:
        asyncio.run(prompt.handle("hi"))
    with caplog.at_level("WARNING", "nlp_api"):
        llm_error(refused.value, "/test")

    assert "Pattern Matching" in caplog.text
    assert "756" not in caplog.text


def test_a_prose_answer_is_logged_without_its_text(
    llm_access, set_redis, monkeypatch, caplog  # noqa: F811
):
    """The answer rewrites the user's sentence, so it must not reach the log."""
    llm_access(LlmAccessType.USERS)

    async def prose(*args, **kwargs):
        return LlmAnswer("Sure! Hey everyone, the chairperson will be late.", None)

    with TestClient(app) as client, caplog.at_level("WARNING", "nlp_api"):
        monkeypatch.setattr(app.state.context.prompt, "answer", prose)
        client.post(
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

    assert "not a JSON object" in caplog.text
    assert "chair" not in caplog.text
