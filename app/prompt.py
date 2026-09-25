import asyncio
import logging

import litellm

from app.settings import Settings
from app.alternatives import Alternatives
import json_repair

# Providers differ in which parameters they accept, and a request that names one
# they do not is an error rather than a warning. Dropping the unsupported ones is
# what lets LLM_MODEL be swapped between providers without touching this file.
litellm.drop_params = True
# Nothing about a check leaves this process except the request to the model.
litellm.telemetry = False
litellm.suppress_debug_info = True


class LlmUnavailable(Exception):
    """The provider is busy, rate limited, unreachable or too slow: worth
    trying again shortly (503)."""


class LlmCutOff(Exception):
    """The answer hit LLM_MAX_TOKENS before it was complete. Using it would
    mean using a truncated sentence or broken JSON."""


# What a provider answers when the fault is load or the network, not the request.
_UNAVAILABLE = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.BadGatewayError,
)


class Prompt:
    settings: Settings
    alternatives: Alternatives

    def __init__(self, settings: Settings):
        self.settings = settings
        self._slots = (
            asyncio.Semaphore(settings.llm_max_concurrency)
            if settings.llm_max_concurrency > 0
            else None
        )

    def _credentials(self, model: str) -> dict:
        """Provider credentials, keyed off the provider prefix in the model id.

        Bedrock signs with a key pair rather than a bearer token, and passing
        empty strings would break a deployment relying on an instance role, so
        the AWS settings are only forwarded when they are actually set.
        """
        if model.startswith("bedrock/"):
            if not self.settings.aws_key:
                return {"aws_region_name": self.settings.aws_region_name or None}

            return {
                "aws_region_name": self.settings.aws_region_name or None,
                "aws_access_key_id": self.settings.aws_key,
                "aws_secret_access_key": self.settings.aws_secret_key,
            }

        return {
            "api_key": self.settings.llm_api_key or None,
            "api_base": self.settings.llm_api_base or None,
        }

    async def handle(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """Handle LLM prompt generation and response.

        Args:
            user_prompt: The user's prompt text
            system_prompt: Optional system prompt (defaults to inclusive language guidelines)
            model: LiteLLM model identifier, e.g. `openai/gpt-4o` (defaults to settings)
            temperature: LLM temperature parameter (defaults to 0.1)
            max_tokens: Maximum number of tokens the LLM generates (defaults
                to LLM_MAX_TOKENS)

        Returns:
            The complete LLM response as a string

        Raises:
            LlmUnavailable: busy, rate limited, unreachable or timed out.
            LlmCutOff: the answer hit max_tokens.
        """
        model = self.settings.resolve_llm_model(model)
        temperature = temperature or 0.1

        if system_prompt is None:
            system_prompt = """
            You are an expert in inclusive language.
            Keep gender equality in mind and avoid language that is needlessly gendered (f.e. use truly gender neutral nouns, avoid pronouns).
            Do not make biased assumptions.
            Do not rely on social stereotypes.
            Do not use derogatory language even as a joke.
            Avoid jargon terms, specially sports or military terms.            

            Specifically make use of communal and inclusive language.

            Follow instructions without mentioning them in your response. Specifically do not add phrases like "Greetings", "Here is .." or "Sure .." to the beginning of your response.
            """

        # A model that has no system role of its own — Bedrock's Mistral ones,
        # among others — gets the system prompt folded into the message by
        # LiteLLM, so it no longer has to be special-cased here.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        timeout = self.settings.llm_timeout
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
                **self._credentials(model),
            )
        except _UNAVAILABLE as error:
            raise LlmUnavailable(str(error)) from error
        finally:
            if self._slots is not None:
                self._slots.release()

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LlmCutOff(
                f"{model} used all {max_tokens or self.settings.llm_max_tokens}"
                " tokens before answering; raise LLM_MAX_TOKENS"
            )

        return choice.message.content or ""

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
            {"Retry-After": "10"},
            "The language model is busy or unreachable, try again shortly",
        )
    if isinstance(error, LlmCutOff):
        logger.error("%s: %s", route, error)
        return 502, {}, "The language model's answer was cut off"

    logger.error("%s failed", route, exc_info=error)
    return 500, {}, "An error occurred"
