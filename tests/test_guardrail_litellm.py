"""The LiteLLM Generic Guardrail API adapter: guidance on the way in, a note
or a block on the way out, in the format LiteLLM expects."""

import pytest

from app.guidance import BASE_GUIDANCE
from tests.test_api import set_redis  # noqa: F401  (fixture)
from tests.test_guardrail import AUTH, llm_calls, post  # noqa: F401  (fixture)

PATH = "/v1.0/guardrail/litellm/beta/litellm_basic_guardrail_api"
FLAGGED = "The chairman called the policemen."
CLEAN = "We support inclusion, diversity and equity."


def call(body, headers=AUTH):
    return post(PATH, {"litellm_call_id": "abc", **body}, headers)


def respond(texts, **params):
    return call(
        {
            "texts": texts,
            "input_type": "response",
            "additional_provider_specific_params": {"lang": "en", **params},
        }
    )


def test_request_gets_guidance(set_redis, llm_calls):  # noqa: F811
    user = {"role": "user", "content": "Write a job ad."}

    response = call(
        {"texts": ["Write a job ad."], "input_type": "request", "structured_messages": [user]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "GUARDRAIL_INTERVENED"
    assert body["structured_messages"][0]["role"] == "system"
    assert body["structured_messages"][0]["content"].startswith(BASE_GUIDANCE)
    assert body["structured_messages"][1] == user


def test_request_with_guidance_already_is_left_alone(set_redis, llm_calls):  # noqa: F811
    user = {"role": "user", "content": "Write a job ad."}
    first = call(
        {"texts": ["Write a job ad."], "input_type": "request", "structured_messages": [user]}
    ).json()["structured_messages"]

    response = call(
        {"texts": ["Write a job ad."], "input_type": "request", "structured_messages": first}
    )

    assert response.json() == {"action": "NONE"}


def test_request_without_messages_is_left_alone(set_redis, llm_calls):  # noqa: F811
    response = call({"texts": ["Some text to embed."], "input_type": "request"})

    assert response.status_code == 200
    assert response.json() == {"action": "NONE"}


def test_response_pass_is_none(set_redis, llm_calls):  # noqa: F811
    response = respond([CLEAN])

    assert response.status_code == 200
    assert response.json() == {"action": "NONE"}


def test_response_fail_is_annotated(set_redis, llm_calls):  # noqa: F811
    response = respond([FLAGGED])

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "GUARDRAIL_INTERVENED"
    assert body["texts"][0].startswith(FLAGGED + "\n\n[Witty] ")
    assert '"chairman" →' in body["texts"][0]


def test_response_fail_can_block(set_redis, llm_calls):  # noqa: F811
    response = respond([FLAGGED], on_fail="block")

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "BLOCKED"
    assert body["blocked_reason"].startswith("Witty: ")
    assert '"chairman" →' in body["blocked_reason"]


def test_texts_stay_one_to_one(set_redis, llm_calls):  # noqa: F811
    response = respond([CLEAN, FLAGGED, "  "])

    texts = response.json()["texts"]
    assert len(texts) == 3
    assert texts[0] == CLEAN
    assert texts[1].startswith(FLAGGED + "\n\n[Witty] ")
    assert texts[2] == "  "


@pytest.mark.parametrize(
    "params", [{"on_fail": "rewrite"}, {"threshold": 0}, {"lang": "xx"}]
)
def test_params_are_validated(set_redis, llm_calls, params):  # noqa: F811
    assert respond([FLAGGED], **params).status_code == 422


def test_requires_a_user(set_redis, llm_calls):  # noqa: F811
    response = call({"texts": [FLAGGED], "input_type": "response"}, headers={})

    assert response.status_code == 401


def test_makes_no_llm_call(set_redis, llm_calls):  # noqa: F811
    assert respond([FLAGGED]).status_code == 200
    assert llm_calls == []
