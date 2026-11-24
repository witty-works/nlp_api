"""Checks every LLM rephrasing passes before it reaches the user.

They look only at the text that came back, so they work whatever model or
provider answered, and each targets a mistake measured on real models
(docs/llm-models.md): the swap undone, an inclusive form turned back, another
occurrence of the flagged words changed, the sentence rewritten, or a word
added that Witty itself flags. A suggestion that fails any of them is
dropped, and the client falls back to the plain alternative. A drop is
logged and counted by the check's name only, never with text (AGENTS.md, 1.1).
"""

import difflib
import logging
import re

from app.context import AppContext
from app.guardrail import utf16_length
from app.language_processor import apply_language_rules, fetch_text
from app.llm_alternatives import RephraseOutcome, Suggestion
from app.models import CheckRequestIn, MetricsType, RephraseRequestIn
from app.version_validators import Client

# How many words outside the alternative a model may change in a draft, for
# the agreement the swap needs (articles, adjectives, pronouns, the verb).
# Calibrated on tests/test_answer_checks: correct answers change at most 2
# ("qu'il est très attentif" -> "qu'elle est très attentive"), a rewrite of
# the sentence many more.
MAX_OTHER_CHANGED_WORDS = 3

# The category whose findings mean the suggestion says what Witty would flag.
GENDER_CATEGORY = "gender-orientation"


def _occurrences(words: str, text: str) -> int:
    """How often `words` occur in `text` as whole words, ignoring case."""
    if not words:
        return 0
    return len(
        re.findall(r"(?<!\w)" + re.escape(words) + r"(?!\w)", text, re.IGNORECASE)
    )


def alternative_missing(
    lang, suggestion: str, alternative: str, context: AppContext
) -> str | None:
    """Every word of the alternative is in the suggestion, by lemma or as
    written, so an inflected form passes ("closely examined" for "closely
    examine") but an undone swap does not ("chairman" for "chair")."""
    suggestion_doc = context.model.fetch_tokens(lang, suggestion)
    lemmas = {token.lemma_.lower() for token in suggestion_doc}
    words = {token.text.lower() for token in suggestion_doc}
    for token in context.model.fetch_tokens(lang, alternative):
        if token.is_punct or token.is_space:
            continue
        if token.lemma_.lower() not in lemmas and token.text.lower() not in words:
            return "alternative_missing"
    return None


def replaced_words_back(
    sentence: str, text: str, suggestion: str, alternative: str
) -> str | None:
    """The flagged words occur no more often than in the original minus the
    replaced occurrence, plus where the alternative itself contains them (a
    binary form such as "Les experts et les expertes")."""
    allowed = _occurrences(text, sentence) - 1 + _occurrences(text, alternative)
    if _occurrences(text, suggestion) > allowed:
        return "replaced_words_back"
    return None


def other_occurrence_changed(
    sentence: str, text: str, suggestion: str, alternative: str
) -> str | None:
    """The other occurrences of the flagged words are still there: only the
    one the user chose to replace may change."""
    expected = _occurrences(text, sentence) - 1 + _occurrences(text, alternative)
    if _occurrences(text, suggestion) < expected:
        return "other_occurrence_changed"
    return None


def too_much_changed(draft: str, model_sentence: str, alternative: str) -> str | None:
    """The model changed at most MAX_OTHER_CHANGED_WORDS words outside the
    alternative, word by word against the draft."""
    before, after = draft.split(), model_sentence.split()
    alternative_words = {word.lower() for word in alternative.split()}
    changed = 0
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        ours = sum(1 for word in before[i1:i2] if word.lower() in alternative_words)
        changed += max(i2 - i1, j2 - j1) - ours
    if changed > MAX_OTHER_CHANGED_WORDS:
        return "too_much_changed"
    return None


def _changed_span(sentence: str, suggestion: str) -> tuple[int, int] | None:
    """Where the suggestion differs from the sentence, in UTF-16 offsets as
    the check reports its findings."""
    matcher = difflib.SequenceMatcher(None, sentence, suggestion, autojunk=False)
    spans = [(j1, j2) for op, _, _, j1, j2 in matcher.get_opcodes() if op != "equal"]
    if not spans:
        return None
    start, end = min(j1 for j1, _ in spans), max(j2 for _, j2 in spans)
    return utf16_length(suggestion[:start]), utf16_length(suggestion[:end])


async def flagged_by_witty(
    request_in: RephraseRequestIn,
    suggestion: str,
    alternative: str,
    configs: dict,
    context: AppContext,
) -> str | None:
    """Witty's own check, with the requesting user's config, finds nothing in
    the gender category where the suggestion differs from the sentence,
    apart from the alternative the user chose: Witty may prefer another
    format than a binary form it offered (it flags "Les experts et expertes"
    and suggests "Les expert·es"), and that choice is the user's, not a
    mistake of the model's. Words the model added are what this catches."""
    span = _changed_span(request_in.sentence, suggestion)
    if span is None:
        return None
    check_in = CheckRequestIn(
        text=suggestion,
        lang=request_in.lang,
        config=request_in.config,
        client=request_in.client,
    )
    text, language, _ = fetch_text(check_in, context.langs, context)
    if language is None:
        return None
    findings = await apply_language_rules(
        Client.parse(request_in.client),
        check_in.config,
        configs,
        language,
        text,
        context,
        languagetool=False,
    )
    start, end = span
    chosen = {word.lower() for word in re.findall(r"[\w·*:/-]+", alternative)}
    for finding in findings:
        if (
            finding.category == GENDER_CATEGORY
            and finding.start < end
            and finding.end > start
            and not {word.lower() for word in re.findall(r"[\w·*:/-]+", finding.text)}
            <= chosen
        ):
            return "flagged_by_witty"
    return None


async def failed_checks(
    request_in: RephraseRequestIn,
    suggestion: Suggestion,
    configs: dict,
    context: AppContext,
) -> list[str]:
    """The names of the checks the suggestion fails, empty if none."""
    sentence, text = request_in.sentence, request_in.text
    failed = [
        alternative_missing(
            request_in.lang, suggestion.text, suggestion.alternative, context
        ),
        replaced_words_back(sentence, text, suggestion.text, suggestion.alternative),
        other_occurrence_changed(
            sentence, text, suggestion.text, suggestion.alternative
        ),
        *(
            too_much_changed(draft, model_sentence, suggestion.alternative)
            for draft, model_sentence in suggestion.drafts
        ),
    ]
    names = list(dict.fromkeys(name for name in failed if name))
    if not names:
        witty = await flagged_by_witty(
            request_in, suggestion.text, suggestion.alternative, configs, context
        )
        if witty:
            names.append(witty)
    return names


async def checked_results(
    request_in: RephraseRequestIn,
    outcome: RephraseOutcome,
    configs: dict,
    context: AppContext,
) -> dict[str, str]:
    """The suggestions that pass every check, keyed by alternative."""
    logger = logging.getLogger("nlp_api")
    results = {}
    for suggestion in outcome.suggestions:
        failed = await failed_checks(request_in, suggestion, configs, context)
        if not failed:
            results[suggestion.alternative] = suggestion.text
            continue
        logger.warning("rephrasing dropped by answer check %s", failed[0])
        if context.settings.log_metrics:
            try:
                context.redis.db.hincrby(MetricsType.REPHRASE_DROPPED, failed[0], 1)
            except Exception:
                logger.warning("could not count %s", MetricsType.REPHRASE_DROPPED)
    return results
