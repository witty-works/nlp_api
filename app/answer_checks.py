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
from dataclasses import dataclass

from app.context import AppContext
from app.language_processor import apply_language_rules, fetch_text
from app.llm_alternatives import RephraseOutcome, Suggestion
from app.models import CheckRequestIn, MetricsType, RephraseRequestIn
from app.version_validators import Client

# How many words outside the alternative a model may change in a draft, for
# the agreement the swap needs (articles, adjectives, pronouns, the verb).
# Agreement changes are not counted (_agreement). Calibrated on
# tests/test_answer_checks: correct answers change at most 2 other words, a
# rewrite of the sentence many more.
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


async def alternative_missing(
    lang, suggestion: str, alternative: str, context: AppContext
) -> str | None:
    """Every word of the alternative is in the suggestion, by lemma or as
    written, so an inflected form passes ("closely examined" for "closely
    examine") but an undone swap does not ("chairman" for "chair"). Parsed
    inside nlp_session, so the user's words do not stay in the model's string
    store; only plain strings leave it."""
    async with context.model.nlp_session(lang):
        suggestion_doc = context.model.fetch_tokens(lang, suggestion)
        lemmas = {token.lemma_.lower() for token in suggestion_doc}
        words = {token.text.lower() for token in suggestion_doc}
        wanted = [
            (token.lemma_.lower(), token.text.lower())
            for token in context.model.fetch_tokens(lang, alternative)
            if not (token.is_punct or token.is_space)
        ]
    for lemma, word in wanted:
        if lemma not in lemmas and word not in words:
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


@dataclass
class _Token:
    """A token reduced to plain strings, so nothing outlives nlp_session."""

    text: str
    lemma_: str
    pos_: str


# Word classes that follow the swapped-in noun (articles, possessives,
# pronouns): changing them is agreement, never a rewrite.
AGREEMENT_POS = {"DET", "PRON"}


def _agreement(before, after) -> bool:
    """A change the swap itself needs: the same word inflected (same lemma)
    or one article or pronoun for another."""
    if before.lemma_ == after.lemma_:
        return True
    return before.pos_ in AGREEMENT_POS and after.pos_ in AGREEMENT_POS


async def too_much_changed(
    draft: str, model_sentence: str, alternative: str, lang, context: AppContext
) -> str | None:
    """The model changed at most MAX_OTHER_CHANGED_WORDS words outside the
    alternative, word by word against the draft. Agreement changes do not
    count (_agreement): a German sentence can need five of them ("er",
    "seinen", "seiner" become "sie", "ihren", "ihrer"). Parsed inside
    nlp_session, as in alternative_missing."""
    async with context.model.nlp_session(lang):
        before = [
            _Token(t.text.lower(), t.lemma_.lower(), t.pos_)
            for t in context.model.fetch_tokens(lang, draft)
            if not (t.is_punct or t.is_space)
        ]
        after = [
            _Token(t.text.lower(), t.lemma_.lower(), t.pos_)
            for t in context.model.fetch_tokens(lang, model_sentence)
            if not (t.is_punct or t.is_space)
        ]
        alternative_words = {
            t.text.lower() for t in context.model.fetch_tokens(lang, alternative)
        }
    changed = 0
    matcher = difflib.SequenceMatcher(
        None, [t.text for t in before], [t.text for t in after], autojunk=False
    )
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        old, new = before[i1:i2], after[j1:j2]
        for index in range(max(len(old), len(new))):
            a = old[index] if index < len(old) else None
            b = new[index] if index < len(new) else None
            if a and a.text in alternative_words:
                continue
            if a and b and _agreement(a, b):
                continue
            if not (a and b) and (a or b).pos_ in AGREEMENT_POS:
                continue
            changed += 1
    if changed > MAX_OTHER_CHANGED_WORDS:
        return "too_much_changed"
    return None


def _words(text: str) -> list[str]:
    """Lowercased words, split at gender separators too ("ihre/seine")."""
    return [word.lower() for word in re.findall(r"\w+", text)]


async def gender_findings(
    request_in: RephraseRequestIn, text: str, configs: dict, context: AppContext
) -> list[str]:
    """The texts Witty's check flags in the gender category, with the
    requesting user's config."""
    check_in = CheckRequestIn(
        text=text,
        lang=request_in.lang,
        config=request_in.config,
        client=request_in.client,
    )
    checked, language, _ = fetch_text(check_in, context.langs, context)
    if language is None:
        return []
    findings = await apply_language_rules(
        Client.parse(request_in.client),
        check_in.config,
        configs,
        language,
        checked,
        context,
        languagetool=False,
    )
    return [finding.text for finding in findings if finding.category == GENDER_CATEGORY]


async def flagged_by_witty(
    request_in: RephraseRequestIn,
    suggestion: str,
    alternative: str,
    configs: dict,
    context: AppContext,
    original_findings: list[str],
) -> str | None:
    """Witty's own check, with the requesting user's config, finds no more
    in the gender category than the original sentence had outside the
    replaced words (`original_findings`). Counted, not matched by text: Witty
    may regroup the same flagged word ("Jeder Lehrer" becomes "Lehrer") and
    flags agreement pronouns too ("seine", "er" become "ihre", "sie").
    Findings made only of the alternative the user chose are not counted:
    Witty may prefer another format than a binary form it offered (it flags
    "Les experts et expertes" and suggests "Les expert·es"), and that choice
    is the user's, not a mistake of the model's. A flagged word the model
    adds is what this catches."""
    replaced = set(_words(request_in.text))
    chosen = set(_words(alternative))
    # The replaced occurrence's own finding is gone by design; any other
    # occurrence of the same words the user kept still counts.
    before = len(original_findings) - (
        1 if any(set(_words(text)) <= replaced for text in original_findings) else 0
    )
    after = sum(
        1
        for text in await gender_findings(request_in, suggestion, configs, context)
        if not set(_words(text)) <= chosen
    )
    if after > before:
        return "flagged_by_witty"
    return None


async def failed_checks(
    request_in: RephraseRequestIn,
    suggestion: Suggestion,
    configs: dict,
    context: AppContext,
    original_findings: list[str] | None = None,
) -> list[str]:
    """The names of the checks the suggestion fails, empty if none.

    A plain suggestion is checked as the model wrote it. A gendered one is
    assembled by Witty from a masculine and a feminine draft, so each draft
    is checked against the form it was made with, and Witty's own check is
    not run on the assembly: with the default config it flags forms Witty
    built itself ("Die/der")."""
    sentence, text = request_in.sentence, request_in.text
    if suggestion.forms:
        checked = [
            (form, model_sentence)
            for form, (_, model_sentence) in zip(suggestion.forms, suggestion.drafts)
        ]
        forms = suggestion.forms
    else:
        checked = [(suggestion.alternative, suggestion.text)]
        forms = [suggestion.alternative] * len(suggestion.drafts)
    failed = []
    for alternative, model_sentence in checked:
        failed += [
            await alternative_missing(
                request_in.lang, model_sentence, alternative, context
            ),
            replaced_words_back(sentence, text, model_sentence, alternative),
            other_occurrence_changed(sentence, text, model_sentence, alternative),
        ]
    for form, (draft, model_sentence) in zip(forms, suggestion.drafts):
        failed.append(
            await too_much_changed(
                draft, model_sentence, form, request_in.lang, context
            )
        )
    names = list(dict.fromkeys(name for name in failed if name))
    if not names and not suggestion.forms:
        if original_findings is None:
            original_findings = await gender_findings(
                request_in, sentence, configs, context
            )
        witty = await flagged_by_witty(
            request_in,
            suggestion.text,
            suggestion.alternative,
            configs,
            context,
            original_findings,
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
    original_findings = await gender_findings(
        request_in, request_in.sentence, configs, context
    )
    for suggestion in outcome.suggestions:
        failed = await failed_checks(
            request_in, suggestion, configs, context, original_findings
        )
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
