"""The checks every rephrasing passes before it reaches the user
(app/answer_checks.py). The cases are model answers measured on 2026-11-24
(docs/llm-models.md): the kept ones are correct, the others are mistakes."""

import asyncio
import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.answer_checks import (
    checked_results,
    failed_checks,
    other_occurrence_changed,
    replaced_words_back,
    too_much_changed,
)
from app.language_processor import apply_language_rules, fetch_text
from app.llm_alternatives import LlmAlternatives, RephraseOutcome, Suggestion
from app.main import app
from app.models import CheckRequestIn, RephraseRequestIn
from app.prompt import LlmAnswer, Prompt
from app.version_validators import Client

CASES = json.loads(
    pathlib.Path(__file__)
    .with_name("test_answer_checks")
    .joinpath("cases.json")
    .read_text()
)


@pytest.fixture(scope="module")
def context():
    with TestClient(app):
        yield app.state.context


def request_for(case):
    return RephraseRequestIn(
        sentence=case["sentence"],
        text=case["text"],
        start=case["start"],
        lang=case["lang"],
        alternatives=[{"text": case["alternative"]}],
    )


def suggestion_for(case):
    return Suggestion(
        alternative=case["alternative"],
        text=case["model_sentence"],
        drafts=[(case["draft"], case["model_sentence"])],
    )


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_fixture_cases(case, context):
    failed = asyncio.run(
        failed_checks(request_for(case), suggestion_for(case), {}, context)
    )
    if case["expected"] == "keep":
        assert failed == []
    else:
        assert case["expected"] in failed


def test_binary_alternative_containing_flagged_words_survives(context):
    case = next(c for c in CASES if c["name"] == "binary_fr_kept")
    outcome = RephraseOutcome({}, None, [suggestion_for(case)])
    results = asyncio.run(checked_results(request_for(case), outcome, {}, context))
    assert results == {case["alternative"]: case["model_sentence"]}


def test_only_failing_suggestions_are_dropped(context):
    kept = next(c for c in CASES if c["name"] == "guys_kept")
    changed = next(c for c in CASES if c["name"] == "second_guys_changed")
    request = RephraseRequestIn(
        sentence=kept["sentence"],
        text=kept["text"],
        start=kept["start"],
        lang="en",
        alternatives=[{"text": "everyone"}, {"text": "all"}],
    )
    bad = suggestion_for(changed)
    bad.alternative = "all"
    bad.text = "When I am with all, I feel like one of all"
    bad.drafts = [("When I am with the all, I feel like one of the guys", bad.text)]
    outcome = RephraseOutcome({}, None, [suggestion_for(kept), bad])
    results = asyncio.run(checked_results(request, outcome, {}, context))
    assert results == {"everyone": kept["model_sentence"]}


def test_a_drop_is_logged_without_text(context, caplog):
    case = next(c for c in CASES if c["name"] == "swap_undone")
    outcome = RephraseOutcome({}, None, [suggestion_for(case)])
    with caplog.at_level("WARNING", "nlp_api"):
        results = asyncio.run(checked_results(request_for(case), outcome, {}, context))
    assert results == {}
    assert "alternative_missing" in caplog.text
    assert "chairman" not in caplog.text and "HACKED" not in caplog.text


def test_agreement_changes_are_not_too_much(context):
    """Pronoun and adjective follow the swapped-in noun: two words, kept."""
    draft = "Nous attendons de notre serveuse qu'il est très attentif aux clients."
    model = "Nous attendons de notre serveuse qu'elle est très attentive aux clients."
    assert (
        asyncio.run(too_much_changed(draft, model, "serveuse", "fr", context)) is None
    )


class CorrectModel(Prompt):
    """Answers each draft with the marks removed and the given fixes applied:
    a model that does the agreement right."""

    fixes: dict = {}

    async def answer(self, user_prompt, *args, **kwargs):
        sentences = json.loads(user_prompt)["sentences"]
        out = {}
        for key, draft in sentences.items():
            sentence = draft.replace("⟦", "").replace("⟧", "")
            for wrong, right in self.fixes.items():
                sentence = sentence.replace(wrong, right)
            out[key] = sentence
        return LlmAnswer(json.dumps(out, ensure_ascii=False), "model")


@pytest.mark.parametrize(
    "sentence,fixes",
    [
        (
            "Jeder Lehrer kennt seine Schüler.",
            {"Jede Lehrerin kennt seine": "Jede Lehrerin kennt ihre"},
        ),
        (
            "Der erfahrene Arzt hat seinen Patienten geholfen.",
            {"Der erfahrene Ärztin hat seinen": "Die erfahrene Ärztin hat ihren"},
        ),
        ("Die Mitarbeiter sind heute da.", {}),
    ],
)
def test_correct_gendered_suggestions_from_witty_alternatives_survive(
    sentence, fixes, context
):
    """Through the real LlmAlternatives with the alternatives Witty itself
    offers for the sentence: a model that answers correctly loses nothing."""
    check_in = CheckRequestIn(text=sentence, lang="de", client="string")
    text, language, _ = fetch_text(check_in, context.langs, context)
    findings = asyncio.run(
        apply_language_rules(
            Client.parse("string"),
            check_in.config,
            {},
            language,
            text,
            context,
            languagetool=False,
        )
    )
    model = CorrectModel(context.settings)
    model.fixes = fixes
    handler = LlmAlternatives(
        context.settings, context.llm_alternatives.alternatives, model
    )
    checked = 0
    for finding in findings:
        if finding.category != "gender-orientation" or not finding.alternatives:
            continue
        alternatives = [
            {
                key: value
                for key, value in alternative.model_dump().items()
                if key
                in (
                    "text",
                    "gender_role",
                    "male_form",
                    "female_form",
                    "collective_noun",
                )
                and value is not None
            }
            for alternative in finding.alternatives
        ]
        request = RephraseRequestIn(
            sentence=sentence,
            text=finding.text,
            start=sentence.find(finding.text),
            lang="de",
            alternatives=alternatives,
            gender_separator="*in",
        )
        outcome = asyncio.run(handler.handle(request.model_copy(deep=True)))
        for suggestion in outcome.suggestions:
            failed = asyncio.run(failed_checks(request, suggestion, {}, context))
            assert failed == [], (suggestion.alternative, suggestion.text, failed)
            checked += 1
    assert checked


def test_the_lemma_check_parses_inside_a_memory_zone(context, monkeypatch):
    """The user's words are parsed inside nlp_session, so they do not stay in
    the model's string store for good."""
    import contextlib

    inside = {"now": False, "outside_calls": 0}
    real_fetch = context.model.fetch_tokens

    @contextlib.asynccontextmanager
    async def session(lang):
        inside["now"] = True
        try:
            yield
        finally:
            inside["now"] = False

    def fetch_tokens(lang, text):
        if not inside["now"]:
            inside["outside_calls"] += 1
        return real_fetch(lang, text)

    monkeypatch.setattr(context.model, "nlp_session", session)
    monkeypatch.setattr(context.model, "fetch_tokens", fetch_tokens)
    case = next(c for c in CASES if c["name"] == "tense_kept")
    asyncio.run(failed_checks(request_for(case), suggestion_for(case), {}, context))
    assert inside["outside_calls"] == 0


def test_partial_word_text_drops_nothing():
    """`text` cut inside a word occurs nowhere as a whole word; the
    occurrence checks then have nothing to count, rather than dropping."""
    sentence = "Der Lehrer hilft."
    suggestion = "Die Lehrperson hilft."
    assert replaced_words_back(sentence, "Lehr", suggestion, "Lehrperson") is None
    assert other_occurrence_changed(sentence, "Lehr", suggestion, "Lehrperson") is None


def test_empty_text_is_refused():
    with pytest.raises(ValidationError):
        RephraseRequestIn(
            sentence="Der Lehrer hilft.",
            text="",
            start=0,
            lang="de",
            alternatives=[{"text": "Lehrperson"}],
        )
