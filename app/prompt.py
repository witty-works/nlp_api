import asyncio
import logging
import time
from dataclasses import dataclass

import litellm

from app.settings import Settings
from app.models import MetricsType
from app.alternatives import Alternatives
from app.guidance import BARE_TEXT_INSTRUCTION, BASE_GUIDANCE
import json_repair

# Providers differ in which parameters they accept, and a request that names one
# they do not is an error rather than a warning. Dropping the unsupported ones is
# what lets LLM_MODEL be swapped between providers without touching this file.
litellm.drop_params = True
# Nothing about a check leaves this process except the request to the model.
litellm.telemetry = False
litellm.suppress_debug_info = True
# The provider's response headers, where a LiteLLM proxy names the model that
# answered (app/llm_provider.py, response_header).
litellm.return_response_headers = True


# The exceptions live with the adapters that raise them; imported here too, so
# `from app.prompt import LlmUnavailable` and the like keep working.
from app.llm_provider import (  # noqa: E402
    LlmCutOff,
    LlmProvider,
    LlmTask,
    LlmTextRefused,
    LlmUnavailable,
    provider_for,
)

__all__ = ["LlmCutOff", "LlmTextRefused", "LlmUnavailable", "Prompt", "llm_error"]


# Seconds a client is asked to wait after a call refused for answering with
# another model than LLM_EXPECTED_MODEL (LLM_MODEL_MISMATCH=refuse).
MISMATCH_RETRY_AFTER = 300


@dataclass
class LlmAnswer:
    """The text of an answer, and the model that gave it, if the provider said."""

    text: str
    served_model: str | None


class Prompt:
    settings: Settings
    alternatives: Alternatives

    def __init__(self, settings: Settings, redis_db=None):
        self.settings = settings
        self.provider: LlmProvider = provider_for(settings)
        # This process's most recent answer: which model gave it, and whether
        # that was LLM_EXPECTED_MODEL (None when nothing is expected).
        self.last_served_model: str | None = None
        self.last_model_matched: bool | None = None
        # Where the per-minute count is kept, shared by every worker; without
        # it there is no per-minute limit.
        self.redis_db = redis_db
        self._slots = (
            asyncio.Semaphore(settings.llm_max_concurrency)
            if settings.llm_max_concurrency > 0
            else None
        )

    def _count_request(self) -> None:
        """Count this call against LLM_MAX_REQUESTS_PER_MINUTE, refusing it
        once the minute's budget is spent. A fixed window per wall-clock
        minute: it can let up to twice the limit through around a minute's
        turn, which the provider's own limit absorbs; what matters is that a
        steady stream cannot exceed it."""
        limit = self.settings.llm_max_requests_per_minute
        if limit <= 0 or self.redis_db is None:
            return

        now = time.time()
        key = f"llm_requests:{int(now // 60)}"
        pipe = self.redis_db.pipeline()
        pipe.incr(key)
        pipe.expire(key, 120)
        count = pipe.execute()[0]
        if count > limit:
            raise LlmUnavailable(
                f"{limit} LLM requests this minute (LLM_MAX_REQUESTS_PER_MINUTE)",
                retry_after=60 - int(now % 60),
            )

    async def handle(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task: LlmTask = "other",
    ) -> str:
        """The text of the model's answer; see `answer`."""
        return (
            await self.answer(user_prompt, system_prompt, temperature, max_tokens, task)
        ).text

    def _record_served_model(self, served: str | None, task: LlmTask) -> None:
        """Note which model answered, and compare it with LLM_EXPECTED_MODEL.
        An unknown model counts as a mismatch when one is expected. Only the
        model's name is logged and counted: no text, no machine, no host."""
        logger = logging.getLogger("nlp_api")
        name = served or "unknown"
        logger.debug("LLM %s call answered by %s", task, name)
        self.last_served_model = served
        expected = self.settings.llm_expected_model
        matched = None
        if expected:
            matched = served is not None and self.provider.same_model(expected, served)
        self.last_model_matched = matched
        self._count(MetricsType.LLM_SERVED_MODELS, name)
        if matched is False:
            logger.warning(
                "LLM answered with %s, expected %s (LLM_EXPECTED_MODEL)",
                name,
                expected,
            )
            self._count(MetricsType.LLM_MODEL_MISMATCHES, name)
            if self.settings.llm_model_mismatch == "refuse":
                # It lasts until the deployment changes: clients are asked to
                # wait minutes, not seconds, rather than retry a paid call.
                raise LlmUnavailable(
                    "served model is not LLM_EXPECTED_MODEL",
                    retry_after=MISMATCH_RETRY_AFTER,
                )

    def _count(self, metric: MetricsType, field: str) -> None:
        if not self.settings.log_metrics or self.redis_db is None:
            return
        try:
            self.redis_db.hincrby(metric, field, 1)
        except Exception:
            # A metric is not worth failing a call for.
            logging.getLogger("nlp_api").warning("could not count %s", metric)

    async def answer(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task: LlmTask = "other",
    ) -> LlmAnswer:
        """Handle LLM prompt generation and response.

        Args:
            user_prompt: The user's prompt text
            system_prompt: Optional system prompt (defaults to inclusive language guidelines)
            temperature: LLM temperature parameter (defaults to 0.1)
            max_tokens: Maximum number of tokens the LLM generates (defaults
                to LLM_MAX_TOKENS)
            task: what the call is for, so the adapter can send different
                parameters for each (LLM_TASK_EXTRA_BODY)

        Returns:
            The complete LLM response as a string

        Raises:
            LlmUnavailable: busy, rate limited, unreachable or timed out.
            LlmCutOff: the answer hit max_tokens.
        """
        model = self.settings.llm_model
        temperature = temperature or 0.1

        if system_prompt is None:
            system_prompt = BASE_GUIDANCE + "\n\n" + BARE_TEXT_INSTRUCTION

        # A model that has no system role of its own — Bedrock's Mistral ones,
        # among others — gets the system prompt folded into the message by
        # LiteLLM, so it no longer has to be special-cased here.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        timeout = self.settings.llm_timeout
        # Before waiting for a slot, so a refused call does not hold one.
        self._count_request()
        try:
            if self._slots is not None:
                await asyncio.wait_for(self._slots.acquire(), timeout)
        except TimeoutError:
            raise LlmUnavailable("no free LLM slot") from None
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                max_tokens=max_tokens or self.settings.llm_max_tokens,
                temperature=temperature,  # Controls randomness (lower = more predictable)
                top_p=1,  # Nucleus sampling parameter
                timeout=timeout,
                # A retry would hold the slot and the provider's quota longer
                # than the client waits; the client can ask again instead.
                num_retries=0,
                **self.provider.call_params(task),
            )
        except Exception as error:
            classified = self.provider.classify_error(error)
            if classified is None:
                raise
            raise classified from error
        finally:
            if self._slots is not None:
                self._slots.release()

        # Recorded first: a cut-off answer was still served by some model, and
        # a mismatch refused with `refuse` takes precedence over the cut-off.
        served = self.provider.served_model(response)
        self._record_served_model(served, task)

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LlmCutOff(
                f"{model} used all {max_tokens or self.settings.llm_max_tokens}"
                " tokens before answering; raise LLM_MAX_TOKENS"
            )

        return LlmAnswer(choice.message.content or "", served)

    def parse_json(self, result: str):
        """Parse and repair potentially malformed JSON from LLM responses.

        Handles common issues (`\\u` escapes inside the JSON are decoded by the
        parser itself):
        - Extra text before/after JSON
        - Malformed JSON structure

        Args:
            result: Raw string output from LLM

        Returns:
            Parsed JSON object or original string if not valid JSON
        """
        if not result:
            return result

        # Extract JSON from text if present
        if "{" in result and "}" in result:
            start = result.find("{")
            end = result.rfind("}") + 1
            result = result[start:end]
        elif not result.startswith('"') or not result.endswith('"'):
            return result

        return json_repair.loads(result)


def llm_error(error: Exception, route: str) -> tuple[int, dict, str]:
    """Status, headers and message for an LLM call that failed, the same for
    every route that makes one. Logged here, so no failure goes unrecorded."""
    logger = logging.getLogger("nlp_api")
    if isinstance(error, LlmUnavailable):
        logger.warning("%s: LLM unavailable: %s", route, error)
        return (
            503,
            {"Retry-After": str(error.retry_after)},
            "The language model is busy or unreachable, try again shortly",
        )
    if isinstance(error, LlmCutOff):
        logger.error("%s: %s", route, error)
        return 502, {}, "The language model's answer was cut off"
    if isinstance(error, LlmTextRefused):
        # Not the reason: a guardrail may quote what it matched, which is the
        # user's text. The user gets it; the log only what refused it.
        logger.warning("%s: refused by the LLM provider (%s)", route, error.guardrail)
        return 422, {}, error.message or error.reason or "Refused by the provider"

    logger.error("%s failed", route, exc_info=error)
    return 500, {}, "An error occurred"
