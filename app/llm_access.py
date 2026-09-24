"""Who a client-facing LLM request is for: resolved and checked once, the same
way for /v1.0/rephrase and /v1.0/write."""

from fastapi import Request, status

from app.auth_service import fetch_user
from app.categories import inclusive_categories
from app.config_manager import fetch_configs_for_request
from app.context import AppContext
from app.models import BaseRequestIn, Config


class LlmRefused(Exception):
    """The request may not use the LLM; `status` and `message` say why."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def llm_user(
    request: Request, request_in: BaseRequestIn, context: AppContext, refusal: str
) -> tuple[str, dict]:
    """The user's email and configs, with `request_in.config` resolved. Raises
    LlmRefused: 401 without a user or a config, 403 (`refusal`) where the user
    may not use the LLM, LLM_ACCESS having had its say by then."""
    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    if user_email is None:
        raise LlmRefused(status.HTTP_401_UNAUTHORIZED, "User not found")

    configs = await fetch_configs_for_request(request_in, user_email, context)
    if not configs:
        raise LlmRefused(status.HTTP_401_UNAUTHORIZED, "User config missing")

    if not request_in.config.llm_alternatives:
        raise LlmRefused(status.HTTP_403_FORBIDDEN, refusal)

    return user_email, configs


def with_inclusive_categories_disabled(config: Config) -> None:
    """Disable the inclusive-language categories for a review check. A new
    list, so a config shared with another request is left as it was."""
    config.disabled_categories = [
        *config.disabled_categories,
        *(c for c in inclusive_categories if c not in config.disabled_categories),
    ]
