"""Route registration for all API endpoints."""

from app.routes import (
    utility,
    auth,
    config_routes,
    rephrase,
    prompt,
    textarea,
    check,
    debug,
)
from app.settings import get_settings


def register_routes(app):
    # Register utility routes
    app.include_router(utility.router, tags=["utility"])

    # Register authentication routes
    app.include_router(auth.router, tags=["auth"])

    # Register configuration management routes
    app.include_router(config_routes.router, tags=["config"])

    # Register rephrase routes
    app.include_router(rephrase.router, tags=["rephrase"])

    # Register prompt routes
    app.include_router(prompt.router, tags=["prompt"])

    # Register textarea demo route
    app.include_router(textarea.router, tags=["textarea"])

    # Register Slack integration routes if enabled
    if get_settings().slack_enabled:
        from app.routes import slack as slack_module

        app.include_router(slack_module.router, tags=["slack"])

    # Register text checking routes (core functionality)
    app.include_router(check.router, tags=["check"])

    # Register debug routes
    app.include_router(debug.router, tags=["debug"])
