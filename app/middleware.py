"""Middleware configuration for security headers, CORS and the auth gate."""

import secure
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Match

from app.auth_service import fetch_user
from app.dependencies import fetch_current_username, fetch_management_username


# Security headers configuration
# Allow Swagger UI assets from jsdelivr and inline scripts/styles used by the
# generated Swagger HTML. Keep default-src restrictive and explicitly allow
# script-src and style-src for docs to render. One method per directive: `set`
# replaces the whole policy, so chaining it sent only the last directive.
csp = (
    secure.ContentSecurityPolicy()
    .default_src("'self'", "cdn.jsdelivr.net")
    .script_src("'self'", "'unsafe-inline'", "cdn.jsdelivr.net")
    .style_src("'self'", "'unsafe-inline'", "cdn.jsdelivr.net")
    # Swagger's inline icons and favicon, and in the /textarea editor's popover
    # its logo (inline) and the learning-bite pictures it links from witty.works.
    .img_src(
        "'self'", "data:", "cdn.jsdelivr.net", "fastapi.tiangolo.com", "www.witty.works"
    )
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
    # Likewise a route with a stricter Content-Security-Policy than the one
    # the docs need (/textarea).
    route_csp = response.headers.get("Content-Security-Policy")

    await secure_headers.set_headers_async(response)

    if route_cache_control is not None:
        response.headers["Cache-Control"] = route_cache_control
    if route_csp is not None:
        response.headers["Content-Security-Policy"] = route_csp

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


def _depends_on(dependant, call) -> bool:
    return any(
        dependency.call is call or _depends_on(dependency, call)
        for dependency in dependant.dependencies
    )


def is_password_protected(request, settings) -> bool:
    """Whether the request's route asks for a username and password of its
    own: the management endpoints behind MANAGEMENT_AUTH_ENABLED, the docs
    and development helpers behind API_DOCS_AUTH_ENABLED. Only while that
    switch is on, since with it off they check nothing."""
    enabled = set()
    if settings.management_auth_enabled:
        enabled.add(fetch_management_username)
    if settings.api_docs_auth_enabled:
        enabled.add(fetch_current_username)
    if not enabled:
        return False

    route = _route_for(request.app, request.method, request.url.path)

    return route is not None and bool(_guards_of(route) & enabled)


# Both are answered once per route or path rather than per request: matching
# goes through every route, the guards through each one's dependency tree.
_ROUTE_GUARDS: dict[int, frozenset] = {}
_PATH_ROUTES: dict[tuple, APIRoute | None] = {}
_PATH_ROUTES_MAX = 1024


def _guards_of(route: APIRoute) -> frozenset:
    guards = _ROUTE_GUARDS.get(id(route))
    if guards is None:
        guards = frozenset(
            guard
            for guard in (fetch_management_username, fetch_current_username)
            if _depends_on(route.dependant, guard)
        )
        _ROUTE_GUARDS[id(route)] = guards

    return guards


def _route_for(app, method: str, path: str) -> APIRoute | None:
    key = (id(app), method, path)
    if key in _PATH_ROUTES:
        return _PATH_ROUTES[key]

    scope = {"type": "http", "method": method, "path": path}
    found = None
    for route in app.routes:
        if isinstance(route, APIRoute) and route.matches(scope)[0] == Match.FULL:
            found = route
            break

    # Bounded: paths are client input, so a flood of made-up ones must not
    # grow it without end.
    if len(_PATH_ROUTES) >= _PATH_ROUTES_MAX:
        _PATH_ROUTES.clear()
    _PATH_ROUTES[key] = found

    return found


async def require_api_key(request, call_next):
    """Refuse requests that do not resolve to a user.

    Only active when the setting is on. It sits in front of the routes rather
    than in each one so that a route added later is closed by default. The
    user it resolves is kept on the request, so the handler does not resolve
    it again (see fetch_user).
    """
    context = getattr(request.app.state, "context", None)

    # Before startup finished there is no context and so nothing to check
    # against; the app is not serving yet either.
    if context is None or not context.settings.require_api_key:
        return await call_next(request)

    # CORS preflight carries no credentials by definition, and answering it
    # with a 401 breaks the browser clients before they ever send the request.
    # Nor does an endpoint that asks for a username and password: it checks
    # those itself, and a key on top would only lock out whoever manages it.
    if (
        request.method == "OPTIONS"
        or is_public_path(request.url.path, context.settings.open_paths())
        or is_password_protected(request, context.settings)
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

    request.state.resolved_user = user_email

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
