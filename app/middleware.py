"""Middleware configuration for security headers, CORS and the auth gate."""

import secure
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth_service import fetch_user


# Security headers configuration
# Allow Swagger UI assets from jsdelivr and inline scripts/styles used by the
# generated Swagger HTML. Keep default-src restrictive and explicitly allow
# script-src and style-src for docs to render.
csp = (
    secure.ContentSecurityPolicy()
    .set("default-src 'self' cdn.jsdelivr.net")
    .set("script-src 'self' 'unsafe-inline' cdn.jsdelivr.net")
    .set("style-src 'self' 'unsafe-inline' cdn.jsdelivr.net")
)
hsts = secure.StrictTransportSecurity().include_subdomains().preload().max_age(31536000)
referrer = secure.ReferrerPolicy().no_referrer()
cache_value = secure.CacheControl().no_cache()
xfo = secure.XFrameOptions().deny()

secure_headers = secure.Secure(
    csp=csp,
    hsts=hsts,
    referrer=referrer,
    cache=cache_value,
    xfo=xfo,
)


async def add_security_headers(request, call_next):
    response = await call_next(request)

    # `secure` overwrites Cache-Control with no-cache, which is right for
    # everything that depends on who is asking. A route that deliberately sets
    # its own keeps it — see /v2.0/categories.
    route_cache_control = response.headers.get("Cache-Control")

    await secure_headers.set_headers_async(response)

    if route_cache_control is not None:
        response.headers["Cache-Control"] = route_cache_control

    return response


def is_public_path(path: str, public_paths) -> bool:
    """Whether a path is reachable without a credential.

    Matched on the exact path, ignoring a trailing slash, rather than as a
    prefix: a prefix match on "/health" would also open "/health-internal",
    and an allowlist that silently covers more than it names is the wrong
    failure direction for this switch.
    """
    candidate = path.rstrip("/") or "/"

    return any(entry.rstrip("/") == candidate for entry in public_paths)


async def require_api_key(request, call_next):
    """Refuse requests that do not resolve to a user.

    Only active when the setting is on. It sits in front of the routes rather
    than in each one so that a route added later is closed by default; the
    cost is that the user is resolved twice on the request path, once here and
    once in the handler.
    """
    context = getattr(request.app.state, "context", None)

    # Before startup finished there is no context and so nothing to check
    # against; the app is not serving yet either.
    if context is None or not context.settings.require_api_key:
        return await call_next(request)

    # CORS preflight carries no credentials by definition, and answering it
    # with a 401 breaks the browser clients before they ever send the request.
    if request.method == "OPTIONS" or is_public_path(
        request.url.path, context.settings.public_paths
    ):
        return await call_next(request)

    try:
        user_email = await fetch_user(
            request, context.settings, context.redis, context.http
        )
    except HTTPException as error:
        return JSONResponse(
            status_code=error.status_code, content={"detail": error.detail}
        )

    if user_email is None:
        # No WWW-Authenticate: there is no registered scheme for an `x-key`
        # header, and announcing an invented one tells a client nothing it can
        # act on. The message names the header instead.
        return JSONResponse(
            status_code=401,
            content={"detail": "A valid API key is required in the x-key header."},
        )

    return await call_next(request)


def setup_middleware(app: FastAPI):
    # Registered before the security headers so that it runs after them:
    # Starlette runs the most recently added middleware first, and a 401 from
    # here should still carry the security headers.
    app.middleware("http")(require_api_key)

    # Security headers middleware
    app.middleware("http")(add_security_headers)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
