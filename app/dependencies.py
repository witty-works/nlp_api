"""FastAPI dependencies for authentication and authorization.

Also provides a DI-friendly accessor for the application context stored on
FastAPI's app.state during lifespan.
"""

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.context import AppContext


def get_app_context(request: Request) -> AppContext:
    context = getattr(request.app.state, "context", None)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Application context is not initialized",
        )
    return context


security = HTTPBasic(auto_error=False)


def _fetch_basic_auth_username(
    context: AppContext,
    credentials: Optional[HTTPBasicCredentials],
    enabled: bool,
) -> str:  # pragma: no cover
    """Check basic auth credentials against the one configured pair.

    `enabled` is whichever switch guards the calling group of endpoints; the
    credentials themselves are the same pair either way, so there is one to
    configure rather than two.
    """
    # Auth is disabled, just proceed. Credentials that arrive anyway are
    # ignored rather than checked against a password nobody configured.
    if not enabled:
        return "anon"

    # Credentials are missing
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify the credentials as usual
    if not context.settings.api_docs_username or not context.settings.api_docs_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Incorrect user configuration",
        )

    correct_username = secrets.compare_digest(
        credentials.username, context.settings.api_docs_username
    )
    correct_password = secrets.compare_digest(
        credentials.password, context.settings.api_docs_password
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


def fetch_current_username(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:  # pragma: no cover
    """Guard the docs UI and the development helpers.

    Off by default, because a locked schema is an obstacle in development and
    the schema itself gives nothing away.
    """
    context = get_app_context(request)

    return _fetch_basic_auth_username(
        context, credentials, context.settings.api_docs_auth_enabled
    )


def fetch_management_username(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:  # pragma: no cover
    """Guard everything that hands out or exposes credentials and configuration.

    Separate from the docs switch and on by default: `API_DOCS_AUTH_ENABLED`
    reads as being about the docs UI, and a deployment that left it alone should
    not thereby be letting anyone mint an API key for any email or read the
    whole settings object back.
    """
    context = get_app_context(request)

    return _fetch_basic_auth_username(
        context, credentials, context.settings.management_auth_enabled
    )
