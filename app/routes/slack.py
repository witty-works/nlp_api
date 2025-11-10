"""
Slack Integration Routes
Handles Slack commands and webhook processing.
"""

from fastapi import APIRouter, Request, HTTPException, status
from slack_bolt.async_app import AsyncAck, AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient as WebClient
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from app.models import CheckRequestIn, Client
from app.config_manager import (
    fetch_configs_for_request,
    fetch_organization_configs_for_request,
)
from app.language_processor import fetch_text, apply_language_rules
from app.bolt import process_command_witty, get_bolt
from app.context import AppContext
from app.settings import get_settings

router = APIRouter()

# Slack Bolt app and handler are initialized at startup via init_slack(context)
bolt = None
bolt_handler = None


def init_slack(context: AppContext) -> None:
    """Initialize Slack Bolt app with AppContext and register listeners."""
    global bolt, bolt_handler
    bolt = get_bolt(get_settings(), context)

    @bolt.command("/witty")  # type: ignore[attr-defined]
    async def handle_command_witty(
        body: dict,
        ack: AsyncAck,
        respond: AsyncRespond,
        client: WebClient,
        context: dict,
    ):  # pragma: no cover
        await ack()

        app_context: AppContext | None = context.get("app_context")
        if app_context is None:
            await respond("Service not ready yet. Please try again shortly.")
            return None

        check_request_in = CheckRequestIn(client="slack:1.0.0", text=body["text"])
        text, language, limit_reached = fetch_text(
            check_request_in, app_context.langs, app_context
        )

        if language is None:
            await respond(f"Witty could not determine a language for '{text}'.")
            return None

        configs = {}

        try:
            user = await client.users_info(user=body["user_id"])
            configs = await fetch_configs_for_request(
                check_request_in, user.data["user"]["profile"]["email"], app_context
            )
        except KeyError:
            pass

        if configs == {} and app_context.settings.slack_organization_id:
            configs = await fetch_organization_configs_for_request(
                check_request_in,
                app_context.settings.slack_organization_id,
                app_context,
            )

        check_request_in.config.__setattr__("alternatives_max_count", None)
        parsed_client = Client.parse(check_request_in.client)
        results = await apply_language_rules(
            parsed_client, check_request_in.config, configs, language, text, app_context
        )

        return await process_command_witty(
            text, language, limit_reached, results, respond
        )

    # Create request handler after registering listeners
    bolt_handler = AsyncSlackRequestHandler(bolt)


@router.post("/slack/commands")
async def post_slack_commands(request: Request):  # pragma: no cover
    if bolt_handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Slack not initialized",
        )
    return await bolt_handler.handle(request)
