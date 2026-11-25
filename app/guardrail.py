"""Witty GPT as a guardrail: guidance for a request to any model, and a review of
what the model answered. Nothing here calls an LLM; the gateway, or /v1.0/write
for our own clients, makes every model call."""

from typing import Any

from fastapi import HTTPException, status

from app.context import AppContext
from app.helper import utf16_offsets
from app.language_processor import apply_language_rules, fetch_text
from app.llm_access import with_inclusive_categories_disabled
from app.models import (
    CheckRequestIn,
    Client,
    GuardrailOutputOut,
    GuardrailThreshold,
    ResultOut,
)
from app.review_prompt import ReviewPrompt
from app.settings import Settings

# How much of an answer is checked, in parts of TEXT_MAX_LENGTH: as much as the
# /textarea editor checks. The rest goes unchecked, which `limit_reached` says.
GUARDRAIL_MAX_LENGTH = 20000


def message_length(message: dict[str, Any]) -> int:
    """The characters of a chat message's text: its `content` as a string, or
    the `text` of its content parts. Images and other parts do not count; the
    guardrail neither reads nor checks them."""
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(
            len(part["text"])
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return 0


def at_most(found: int, limit: int, what: str, setting: str) -> None:
    """Refuse a request with more `what` than `limit` with a 422, as
    /v1.0/write refuses a text that is too long. The message names the setting
    for the operator, and quotes nothing of the request."""
    if found > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The request has {found} {what}, more than the {limit} this"
            f" deployment takes per guardrail request ({setting})",
        )


def messages_within_limits(messages: list[dict[str, Any]], settings: Settings) -> None:
    """Chat messages are passed back, not checked: bounded by count and by
    the characters of their text."""
    at_most(
        len(messages),
        settings.guardrail_messages_max_count,
        "messages",
        "GUARDRAIL_MESSAGES_MAX_COUNT",
    )
    at_most(
        sum(message_length(message) for message in messages),
        settings.guardrail_request_max_length,
        "characters",
        "GUARDRAIL_REQUEST_MAX_LENGTH",
    )


# Where a part may end, best first: after a sentence, else at a space.
SENTENCE_ENDS = (". ", "! ", "? ", "\n")


def parts(text: str, size: int) -> list[tuple[int, str]]:
    """`text` cut into parts of at most `size` characters, each with where it
    starts: after a sentence where one ends in the second half of a part,
    else at a space, else wherever `size` falls."""
    result = []
    start = 0
    while len(text) - start > size:
        window = text[start : start + size]
        cut = max(window.rfind(end) + len(end) for end in SENTENCE_ENDS)
        if cut <= size // 2:
            cut = window.rfind(" ") + 1
        if cut <= 0:
            cut = size
        result.append((start, window[:cut]))
        start += cut
    if start < len(text):
        result.append((start, text[start:]))
    return result


def utf16_length(text: str) -> int:
    """`text`'s length in the offsets findings use."""
    offsets = utf16_offsets(text)
    return offsets["chars"][-1] if offsets else len(text)


# What the guardrail fails on where nothing says otherwise: the first finding
# it has alternatives for.
DEFAULT_THRESHOLD = GuardrailThreshold.parse(1)


def finding_level(finding: ResultOut) -> str | None:
    """The level a finding counts towards, as the dashboard colours them: the
    organisation's term rules, then by gravity. None without a gravity."""
    if finding.category == "corporate_rules":
        return "corporate_rules"
    if finding.gravity is None:
        return None
    if finding.gravity < 1.5:
        return "openly_discriminating"
    if finding.gravity <= 2.5:
        return "basic"
    return "advanced"


def failed_on(
    findings: list[ResultOut], words: int, threshold: GuardrailThreshold
) -> list[str]:
    """The levels whose limit the findings with alternatives reach, `ratio`
    measured per word of the `words` checked."""
    counts = {"overall": 0}
    for finding in findings:
        if not finding.alternatives:
            continue
        counts["overall"] += 1
        level = finding_level(finding)
        if level is not None:
            counts[level] = counts.get(level, 0) + 1

    failed = []
    for level in GuardrailThreshold.model_fields:
        limit = getattr(threshold, level)
        if limit is None:
            continue
        found = counts.get(level, 0)
        if (limit.count is not None and found >= limit.count) or (
            limit.ratio is not None and words and found / words >= limit.ratio
        ):
            failed.append(level)

    return failed


def reask_findings(
    findings: list[ResultOut], threshold: GuardrailThreshold
) -> list[ResultOut]:
    """The findings the reask asks the model to fix: those of every level the
    threshold sets a limit for, whether or not that limit was reached. A level
    without a limit is reported and left to the person; with an `overall`
    limit, which the default has, that is every finding."""
    if threshold.overall is not None:
        return findings
    return [
        finding
        for finding in findings
        if (level := finding_level(finding)) is not None
        and getattr(threshold, level) is not None
    ]


async def review(
    check_request_in: CheckRequestIn,
    configs: dict,
    context: AppContext,
) -> GuardrailOutputOut:
    """Check a model's answer against the config's `guardrail_threshold` and,
    where it fails, write the message that asks the model to apply Witty's
    alternatives: those of every level with a limit (reask_findings), not
    only of the levels that failed.

    Never refuses: an answer longer than Witty checks at once is checked in
    parts of TEXT_MAX_LENGTH, up to GUARDRAIL_MAX_LENGTH (`limit_reached` past
    that), with each finding's offsets into the whole answer. One whose
    language cannot be told passes. LanguageTool is not asked.
    """
    with_inclusive_categories_disabled(check_request_in.config)

    answer = check_request_in.text
    limit_reached = len(answer) > GUARDRAIL_MAX_LENGTH
    client = Client.parse(check_request_in.client)

    findings = []
    words = 0
    language = None
    for start, part in parts(
        answer[:GUARDRAIL_MAX_LENGTH], context.settings.text_max_length
    ):
        part_in = CheckRequestIn(
            text=part, lang=check_request_in.lang, config=check_request_in.config
        )
        text, part_language, _ = fetch_text(part_in, context.langs, context)
        if part_language is None:
            continue

        language = language or part_language
        words += len(text.split())
        shift = utf16_length(answer[:start])
        for finding in await apply_language_rules(
            client,
            check_request_in.config,
            configs,
            part_language,
            text,
            context,
            # Spelling, grammar and style are not what the guardrail is for,
            # and a LanguageTool outage must not take down every model call
            # behind it.
            languagetool=False,
        ):
            finding.start += shift
            finding.end += shift
            findings.append(finding)

    if language is None:
        return GuardrailOutputOut(
            verdict="pass", findings=[], limit_reached=limit_reached
        )

    threshold = check_request_in.config.guardrail_threshold or DEFAULT_THRESHOLD
    # Per word of what was checked: past GUARDRAIL_MAX_LENGTH, the unchecked
    # rest would only water a ratio down.
    failed = failed_on(findings, words, threshold)
    reask = (
        ReviewPrompt.handle(reask_findings(findings, threshold), check_request_in.text)
        if failed
        else None
    )

    return GuardrailOutputOut(
        verdict="fail" if failed else "pass",
        findings=findings,
        language=language.lang,
        limit_reached=limit_reached,
        reask=None if reask is None else {"role": "user", "content": reask},
        failed_on=failed or None,
    )
