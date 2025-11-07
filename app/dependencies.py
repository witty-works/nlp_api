"""FastAPI dependencies for authentication and authorization.

Also provides a DI-friendly accessor for the application context stored on
FastAPI's app.state during lifespan. No legacy global context fallback.
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


def fetch_current_username(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:  # pragma: no cover
    # Resolve context (used below)
    context = get_app_context(request)

    # Credentials are missing
    if not credentials:
        # Auth is disabled, just proceed
        if not context.settings.api_docs_auth_enabled:
            return "anon"

        # Auth is enabled, raise 401
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
