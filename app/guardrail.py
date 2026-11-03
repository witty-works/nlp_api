"""Witty GPT as a guardrail: guidance for a request to any model, and a review of
what the model answered. Nothing here calls an LLM; the gateway, or /v1.0/write
for our own clients, makes every model call."""

from app.context import AppContext
from app.language_processor import apply_language_rules, fetch_text
from app.llm_access import with_inclusive_categories_disabled
from app.models import CheckRequestIn, Client, GuardrailOutputOut
from app.review_prompt import ReviewPrompt


async def review(
    check_request_in: CheckRequestIn,
    configs: dict,
    context: AppContext,
    threshold: int = 1,
) -> GuardrailOutputOut:
    """Check a model's answer and, where at least `threshold` findings have
    alternatives, write the message that asks the model to apply them.

    Never refuses: an answer longer than Witty checks at once is checked in
    part (`limit_reached`), and one whose language cannot be told passes.
    LanguageTool is not asked.
    """
    with_inclusive_categories_disabled(check_request_in.config)

    text, language, limit_reached = fetch_text(check_request_in, context.langs, context)
    if language is None:
        return GuardrailOutputOut(
            verdict="pass", findings=[], limit_reached=limit_reached
        )

    findings = await apply_language_rules(
        Client.parse(check_request_in.client),
        check_request_in.config,
        configs,
        language,
        text,
        context,
        # Spelling, grammar and style are not what the guardrail is for, and
        # a LanguageTool outage must not take down every model call behind it.
        languagetool=False,
    )

    reask = ReviewPrompt.handle(
        findings, check_request_in.text, min_changes=threshold - 1
    )

    return GuardrailOutputOut(
        verdict="pass" if reask is None else "fail",
        findings=findings,
        language=language.lang,
        limit_reached=limit_reached,
        reask=None if reask is None else {"role": "user", "content": reask},
    )
