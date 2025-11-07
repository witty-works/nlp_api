import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.startup import lifespan

from app.middleware import setup_middleware
from app.routes import register_routes
from app.context import AppContext

context = AppContext()


# Create FastAPI application with lifecycle management
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Wrapper for lifespan with context."""
    async with lifespan(app, context):
        yield


app = FastAPI(
    title="Witty NLP API",
    version=context.version,
    terms_of_service=context.settings.terms_of_service,
    contact=context.settings.contact,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=app_lifespan,
)

# Setup middleware (security headers, CORS)
setup_middleware(app)

# Register all route modules
register_routes(app)

# Initialize Slack Bolt app and handlers with AppContext if enabled
if context.settings.slack_enabled:
    try:
        from app.routes import slack as slack_routes

        slack_routes.init_slack(context)
    except (AttributeError, TypeError, RuntimeError) as e:
        # Slack is optional; log and continue if initialization is not supported in this environment
        if hasattr(context, "logger"):
            context.logger.warning(f"Slack initialization skipped: {e}")


# Main entry point for direct execution
if __name__ == "__main__":  # pragma: no cover
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=context.settings.logger_config_level,
        server_header=False,
    )
