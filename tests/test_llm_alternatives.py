"""What the rephrasing makes of an LLM answer it cannot use."""

import asyncio
import json

import pytest

from app.llm_alternatives import LlmAlternatives
from app.models import RephraseRequestIn
from app.prompt import Prompt
from app.settings import Settings


class Answering(Prompt):
    def __init__(self, settings, answer):
        super().__init__(settings)
        self.answer = answer

    async def handle(self, *args, **kwargs):
        return self.answer


def rephrase(answer):
    settings = Settings(llm_model="openai/test")
    request = RephraseRequestIn(
        sentence="Der Lehrer gibt dem Schüler den Stift.",
        text="Der Lehrer",
        start=0,
        lang="de",
        alternatives=[{"text": "Die Lehrkraft"}, {"text": "Die Lehrperson"}],
    )
    handler = LlmAlternatives(settings, None, Answering(settings, answer))

    return asyncio.run(handler.handle(request))


@pytest.mark.parametrize(
    "answer",
    [
        # A reasoning model stopped by the token limit mid-thought.
        'Let me analyze this task:\n\n1. The sentence is: "Der Lehrer gibt',
        '["Die Lehrkraft gibt dem Schüler den Stift."]',
        "",
    ],
)
def test_an_answer_that_is_not_an_object_gives_no_rephrasings(answer):
    assert rephrase(answer) == {}


def test_only_sentences_are_kept():
    answer = (
        '{"Die Lehrkraft": "Die Lehrkraft gibt dem Schüler den Stift.",'
        ' "Die Lehrperson": ["not", "a", "sentence"]}'
    )

    assert rephrase(answer) == {
        "Die Lehrkraft": "Die Lehrkraft gibt dem Schüler den Stift."
    }


class Recording(Answering):
    async def handle(self, user_prompt, *args, **kwargs):
        self.user_prompt = user_prompt
        return self.answer


def test_the_code_swaps_the_words_in_and_marks_them():
    """The model gets each sentence with the alternative already in place and
    marked, so it knows which words to adapt: the replaced occurrence, not
    another one like it."""
    settings = Settings(llm_model="openai/test")
    prompt = Recording(settings, "{}")
    request = RephraseRequestIn(
        sentence="When I am with the guys, I feel like one of the guys",
        text="guys",
        start=19,
        lang="en",
        alternatives=[{"text": "everyone"}],
    )
    asyncio.run(LlmAlternatives(settings, None, prompt).handle(request))

    sent = json.loads(prompt.user_prompt)
    assert sent["sentences"] == {
        "everyone": "When I am with the ⟦everyone⟧, I feel like one of the guys"
    }


def test_marks_the_model_left_in_are_removed():
    answer = '{"Die Lehrkraft": "⟦Die Lehrkraft⟧ gibt dem Schüler den Stift."}'

    assert rephrase(answer) == {
        "Die Lehrkraft": "Die Lehrkraft gibt dem Schüler den Stift."
    }
