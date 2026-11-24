"""The parts of an LLM call that differ between providers, as named adapters.

A deployment picks one with LLM_PROVIDER; the API never guesses it from the
model id or the URL, since a LiteLLM proxy, vLLM and OpenAI all answer to
`openai/…`. Adapters live here, and a provider that differs structurally gets
one by pull request; one that only differs in a detail is adjusted with a
setting (LLM_SERVED_MODEL_HEADER, LLM_TASK_EXTRA_BODY). See docs/llm-models.md.
"""

import re
from typing import ClassVar, Literal, get_args

import litellm

from app.settings import Settings

# What a call is for, so an adapter can send different parameters for each
# (for example, no thinking for a rephrasing).
LlmTask = Literal["rephrase", "write", "other"]
LLM_TASKS = get_args(LlmTask)


class LlmUnavailable(Exception):
    """The provider is busy, rate limited, unreachable or too slow: worth
    trying again shortly (503), after `retry_after` seconds."""

    def __init__(self, message: str, retry_after: int = 10):
        super().__init__(message)
        self.retry_after = retry_after


class LlmCutOff(Exception):
    """The answer hit LLM_MAX_TOKENS before it was complete. Using it would
    mean using a truncated sentence or broken JSON."""


class LlmTextRefused(Exception):
    """The provider refused the text itself: a guardrail of the gateway in
    front of the model, or the provider's content filter. Which texts are
    refused depends on the deployment's provider, not on Witty. `reason` is
    the provider's own explanation, when it gives one; `message` the
    deployment's (LLM_REFUSED_MESSAGE), when it has one. `guardrail` names
    what refused it, for the log: the reason may quote the text."""

    def __init__(
        self, reason: str | None, message: str = "", guardrail: str = "content filter"
    ):
        super().__init__(guardrail)
        self.reason = reason
        self.message = message
        self.guardrail = guardrail


# What a provider answers when the fault is load or the network, not the request.
_UNAVAILABLE = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.BadGatewayError,
)


def _refusal(error: litellm.BadRequestError) -> LlmTextRefused | None:
    """An LlmTextRefused if the bad request is a refusal of the text, else None.
    A LiteLLM proxy names the guardrail that refused it in the error body; a
    content filter (OpenAI, Azure) arrives as ContentPolicyViolationError."""
    if isinstance(error, litellm.ContentPolicyViolationError):
        return LlmTextRefused(None)
    body = error.body if isinstance(error.body, dict) else {}
    fields = body.get("provider_specific_fields")
    if isinstance(fields, dict) and fields.get("guardrail_name"):
        reason = fields.get("error") or body.get("message")
        return LlmTextRefused(
            reason if isinstance(reason, str) else None,
            guardrail=str(fields["guardrail_name"]),
        )
    return None


# How long a model name may be wherever it is shown, logged or counted: it
# comes from the provider, and a Redis hash field per name must stay bounded.
MODEL_NAME_MAX_LENGTH = 200
# The account id in an AWS ARN (a Bedrock inference profile, for instance).
_ARN_ACCOUNT = re.compile(r"(arn:aws[\w-]*:[\w-]+:[\w-]*:)\d{12}(:)")


def public_model_name(name: str | None) -> str | None:
    """A model name as it may be shown, logged or counted: an AWS account id
    in an ARN masked, and at most MODEL_NAME_MAX_LENGTH characters."""
    if not name:
        return name
    return _ARN_ACCOUNT.sub(r"\1…\2", name)[:MODEL_NAME_MAX_LENGTH]


def response_header(response, name: str) -> str | None:
    """A response header of the provider's, as LiteLLM passes it on.

    The one place that reads LiteLLM's `_hidden_params`, which is not public
    API: if an upgrade moves it, this returns None (the model is then
    unknown) and tests/test_llm_provider.py fails.
    """
    try:
        headers = response._hidden_params["additional_headers"]
        value = headers.get("llm_provider-" + name.lower())
    except (AttributeError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) and value else None


class LlmProvider:
    """The default: today's behaviour, for any provider LiteLLM speaks to
    directly. Subclasses change only what differs."""

    name: ClassVar[str] = "openai-compatible"

    def __init__(self, settings: Settings):
        self.settings = settings

    def call_params(self, task: LlmTask) -> dict:
        """Credentials and extra request fields for a call. Nothing is derived
        from the model id: a provider without a key of ours (Bedrock) gets
        None, and LiteLLM finds its credentials itself."""
        params = {
            "api_key": self.settings.llm_api_key or None,
            "api_base": self.settings.llm_api_base or None,
        }
        if self.settings.aws_region_name:
            params["aws_region_name"] = self.settings.aws_region_name
        # One level deep: a task's {"chat_template_kwargs": {...}} adds to the
        # global one's instead of replacing it.
        extra_body = dict(self.settings.llm_extra_body)
        for name, value in self.settings.llm_task_extra_body.get(task, {}).items():
            if isinstance(value, dict) and isinstance(extra_body.get(name), dict):
                extra_body[name] = {**extra_body[name], **value}
            else:
                extra_body[name] = value
        if extra_body:
            params["extra_body"] = extra_body
        return params

    def served_model(self, response) -> str | None:
        """The model that answered, as the provider reports it in the body."""
        model = getattr(response, "model", None)
        return model if isinstance(model, str) and model else None

    def same_model(self, expected: str, served: str) -> bool:
        return expected == served

    def classify_error(self, error: Exception) -> Exception | None:
        """The exception to raise for a provider error, or None to re-raise
        it as it is. Recognises a LiteLLM proxy's guardrail refusals here too,
        so a proxy deployment that never set LLM_PROVIDER keeps its 422."""
        if isinstance(error, _UNAVAILABLE):
            return LlmUnavailable(str(error))
        if isinstance(error, litellm.BadRequestError):
            refused = _refusal(error)
            if refused is not None:
                refused.message = self.settings.llm_refused_message
            return refused
        return None


class OpenAiCompatibleProvider(LlmProvider):
    """vLLM, Ollama and other servers that speak the OpenAI API, and any
    provider LiteLLM reaches directly. The body names the served model."""

    name = "openai-compatible"


class LiteLlmProxyProvider(LlmProvider):
    """A LiteLLM proxy: the body repeats the requested alias, and the model
    behind it is named in a response header (LLM_SERVED_MODEL_HEADER)."""

    name = "litellm-proxy"

    def served_model(self, response) -> str | None:
        return response_header(response, self.settings.llm_served_model_header)


class OpenAiProvider(LlmProvider):
    """OpenAI itself: the body names the dated model that answered."""

    name = "openai"


PROVIDERS: dict[str, type[LlmProvider]] = {
    provider.name: provider
    for provider in (OpenAiCompatibleProvider, LiteLlmProxyProvider, OpenAiProvider)
}


def provider_for(settings: Settings) -> LlmProvider:
    """The adapter LLM_PROVIDER names."""
    try:
        return PROVIDERS[settings.llm_provider](settings)
    except KeyError:
        raise ValueError(
            f"LLM_PROVIDER {settings.llm_provider!r} is not one of: "
            + ", ".join(PROVIDERS)
        ) from None
