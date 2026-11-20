"""Route registration for all API endpoints."""

from app.routes import (
    utility,
    auth,
    config_routes,
    rephrase,
    prompt,
    guardrail,
    guardrail_litellm,
    textarea,
    check,
    lt,
    debug,
)
from app.route_table import include
from app.settings import get_settings


def register_routes(app):
    # Register utility routes
    include(app, utility.router, tags=["utility"])

    # Register authentication routes
    include(app, auth.router, tags=["auth"])

    # Register configuration management routes
    include(app, config_routes.router, tags=["config"])

    # Register rephrase routes
    include(app, rephrase.router, tags=["rephrase"])

    # Register /v1.0/write, Witty GPT's managed loop
    include(app, prompt.router, tags=["guardrail"])

    # Register the guardrail routes, for LLM and agent gateways
    include(app, guardrail.router, tags=["guardrail"])
    include(app, guardrail_litellm.router, tags=["guardrail"])

    # Register textarea demo route
    include(app, textarea.router, tags=["textarea"])

    # Register Slack integration routes if enabled
    if get_settings().slack_enabled:
        from app.routes import slack as slack_module

        include(app, slack_module.router, tags=["slack"])

    # Register text checking routes (core functionality)
    include(app, check.router, tags=["check"])

    # Register the LanguageTool-compatible API (under the /lt prefix). With
    # LANGUAGETOOL_COMPAT_ROOT on, additionally at the root (/v2/...) — the
    # exact path layout of a real LanguageTool server — for clients that
    # cannot be given a path in their server URL.
    include(app, lt.router, prefix="/lt", tags=["languagetool"])
    if get_settings().languagetool_compat_root:
        include(app, lt.router, tags=["languagetool"], include_in_schema=False)

    # Register debug routes
    include(app, debug.router, tags=["debug"])
