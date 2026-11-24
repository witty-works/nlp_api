"""The checks every rephrasing passes before it reaches the user
(app/answer_checks.py). The cases are model answers measured on 2026-11-24
(docs/llm-models.md): the kept ones are correct, the others are mistakes."""

import asyncio
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.answer_checks import checked_results, failed_checks, too_much_changed
from app.llm_alternatives import RephraseOutcome, Suggestion
from app.main import app
from app.models import RephraseRequestIn

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


def test_agreement_changes_are_not_too_much():
    """Pronoun and adjective follow the swapped-in noun: two words, kept."""
    draft = "Nous attendons de notre serveuse qu'il est très attentif aux clients."
    model = "Nous attendons de notre serveuse qu'elle est très attentive aux clients."
    assert too_much_changed(draft, model, "serveuse") is None
