"""The guardrail primitives and /v1.0/guardrail/*: guidance for the request,
a verdict and a reask for the response, and never an LLM call of their own."""

import asyncio

import pytest

from app.guardrail import (
    BARE_TEXT_INSTRUCTION,
    BASE_GUIDANCE,
    guidance,
    merge_guidance,
)
from app.models import Config, GermanGenderEndingType, LangWithAutoType
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
