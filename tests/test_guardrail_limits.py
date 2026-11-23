"""How much one guardrail request may ask of the server: at each limit it is
answered, one over it is refused with a 422 that names the setting."""

import pytest

from app.guardrail import GUARDRAIL_MAX_LENGTH
from app.main import context
from app.routes.guardrail_litellm import WITTY_NOTE, checked_length
from app.settings import Settings
from tests.test_api import set_redis  # noqa: F401  (fixture)
from tests.test_guardrail import llm_calls, post  # noqa: F401  (fixture)
from tests.test_guardrail_litellm import call, respond

USER = "Write a job ad."


@pytest.fixture
def limits(monkeypatch):
    def set_limits(**values):
        for name, value in values.items():
            monkeypatch.setattr(context.settings, f"guardrail_{name}", value)

    return set_limits


def refused(response, setting):
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert setting in detail
    # The request's text stays out of the answer.
    assert "job ad" not in detail
    return detail


def user_messages(count, content=USER):
    return [{"role": "user", "content": content}] * count


def test_input_messages_at_and_over_the_count(
    set_redis, llm_calls, limits  # noqa: F811
):
    limits(messages_max_count=3)

    response = post("/v1.0/guardrail/input", {"messages": user_messages(3)})
    assert response.status_code == 200

    response = post("/v1.0/guardrail/input", {"messages": user_messages(4)})
    detail = refused(response, "GUARDRAIL_MESSAGES_MAX_COUNT")
    assert "4 messages" in detail and "the 3 " in detail


@pytest.mark.parametrize("parts", [False, True], ids=["string", "content parts"])
def test_input_characters_at_and_over_the_length(
    parts, set_redis, llm_calls, limits  # noqa: F811
):
    limits(request_max_length=2 * len(USER))

    def content(text):
        return [{"type": "text", "text": text}] if parts else text

    at = [
        {"role": "system", "content": content(USER)},
        {"role": "user", "content": content(USER)},
    ]
    response = post("/v1.0/guardrail/input", {"messages": at})
    assert response.status_code == 200

    over = [*at[:1], {"role": "user", "content": content(USER + "!")}]
    response = post("/v1.0/guardrail/input", {"messages": over})
    refused(response, "GUARDRAIL_REQUEST_MAX_LENGTH")


def test_output_response_at_and_over_the_length(
    set_redis, llm_calls, limits  # noqa: F811
):
    answer = "We support inclusion, diversity and equity."
    limits(request_max_length=len(answer))

    response = post("/v1.0/guardrail/output", {"response": answer, "lang": "en"})
    assert response.status_code == 200

    response = post("/v1.0/guardrail/output", {"response": answer + "!", "lang": "en"})
    refused(response, "GUARDRAIL_REQUEST_MAX_LENGTH")


def test_litellm_request_messages_at_and_over_the_count(
    set_redis, llm_calls, limits  # noqa: F811
):
    limits(messages_max_count=2)

    def request(count):
        return call(
            {
                "texts": [USER] * count,
                "input_type": "request",
                "structured_messages": user_messages(count),
            }
        )

    assert request(2).status_code == 200
    refused(request(3), "GUARDRAIL_MESSAGES_MAX_COUNT")


def test_litellm_request_texts_at_and_over_the_count(
    set_redis, llm_calls, limits  # noqa: F811
):
    """Texts alone, without structured_messages, count as messages too."""
    limits(messages_max_count=2)

    def request(count):
        return call({"texts": [USER] * count, "input_type": "request"})

    assert request(2).status_code == 200
    refused(request(3), "GUARDRAIL_MESSAGES_MAX_COUNT")


def test_litellm_request_characters_at_and_over_the_length(
    set_redis, llm_calls, limits  # noqa: F811
):
    """Texts and messages together."""
    limits(request_max_length=2 * len(USER))

    def request(text):
        return call(
            {
                "texts": [text],
                "input_type": "request",
                "structured_messages": user_messages(1),
            }
        )

    assert request(USER).status_code == 200
    refused(request(USER + "!"), "GUARDRAIL_REQUEST_MAX_LENGTH")


def test_litellm_answer_texts_at_and_over_the_count(
    set_redis, llm_calls, limits  # noqa: F811
):
    limits(texts_max_count=2)
    clean = "We support inclusion."

    assert respond([clean] * 2).status_code == 200
    refused(respond([clean] * 3), "GUARDRAIL_TEXTS_MAX_COUNT")


def test_litellm_answer_characters_at_and_over_the_check_length(
    set_redis, llm_calls, limits  # noqa: F811
):
    clean = "We support inclusion."
    limits(check_max_length=2 * len(clean))

    assert respond([clean, clean]).status_code == 200
    refused(respond([clean, clean + "!"]), "GUARDRAIL_CHECK_MAX_LENGTH")


def test_litellm_answer_with_a_note_counts_twice(
    set_redis, llm_calls, limits  # noqa: F811
):
    """An answer carrying a Witty note may be checked without it and whole."""
    clean = "We support inclusion."
    noted = clean + WITTY_NOTE + "x"
    limits(check_max_length=len(noted) + len(clean))

    assert respond([noted]).status_code == 200

    limits(check_max_length=len(noted) + len(clean) - 1)
    refused(respond([noted]), "GUARDRAIL_CHECK_MAX_LENGTH")


def test_the_defaults_take_a_full_length_answer_with_a_note():
    """GUARDRAIL_CHECK_MAX_LENGTH is twice what one answer is checked up to,
    so the longest answer the check reads passes even when it carries an
    earlier note."""
    settings = Settings()
    noted = "a " * GUARDRAIL_MAX_LENGTH + WITTY_NOTE + "x"

    assert checked_length(noted) == 2 * GUARDRAIL_MAX_LENGTH
    assert checked_length(noted) <= settings.guardrail_check_max_length
    assert settings.guardrail_texts_max_count == 20
    assert settings.guardrail_messages_max_count == 1000
    assert settings.guardrail_request_max_length == 1000000
