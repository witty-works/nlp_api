"""Middleware configuration for security headers, CORS and the auth gate."""

import secure
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth_service import fetch_user
from app.dependencies import fetch_current_username, fetch_management_username
from app.route_table import registered_routes
from app.settings import get_settings


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

    return any((entry.rstrip("/") or "/") == candidate for entry in public_paths)


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

    found = None
    for prefix, route in registered_routes(app):
        if not isinstance(route, APIRoute):
            continue
        if prefix and not (path == prefix or path.startswith(prefix + "/")):
            continue
        scope = {"type": "http", "method": method, "path": path[len(prefix) :]}
        if route.matches(scope)[0] == Match.FULL:
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
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
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


class BodyTooLarge(HTTPException):
    """A request body over REQUEST_MAX_BYTES, found while it was read.

    An HTTPException so that FastAPI passes it on as it is rather than turning
    it into a 400 for a body that could not be parsed."""

    def __init__(self, limit: int):
        super().__init__(
            status_code=413,
            detail=f"The request body is larger than {limit} bytes (REQUEST_MAX_BYTES).",
        )


class RequestSizeLimit:
    """Refuse a request body over REQUEST_MAX_BYTES with a 413.

    Before anything reads it where the request says its length, and while it
    is read where it does not (chunked) or says less than it sends. Pure ASGI
    rather than a BaseHTTPMiddleware, so it sees the body as it arrives
    instead of after it was read whole."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        context = getattr(scope["app"].state, "context", None)
        settings = context.settings if context is not None else get_settings()
        limit = settings.request_max_bytes

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    await self.refuse(scope, receive, send, limit)
                    return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge(limit)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyTooLarge:
            # Where a route read the body outside FastAPI's error handling.
            if started:
                raise
            await self.refuse(scope, receive, send, limit)

    @staticmethod
    async def refuse(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        error = BodyTooLarge(limit)
        response = JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            # The rest of the body is not read, so the connection cannot
            # carry another request.
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)


def setup_middleware(app: FastAPI):
    # Registered first, so it runs last, inside the others: a 413 still
    # carries the security and CORS headers, and browser clients can read it.
    # No middleware before it reads the body.
    app.add_middleware(RequestSizeLimit)

    # Registered before the security headers so that it runs after them:
    # Starlette runs the most recently added middleware first, and a 401 from
    # here should still carry the security headers.
    app.middleware("http")(require_api_key)

    # Security headers middleware
    app.middleware("http")(add_security_headers)

    # CORS middleware. Any origin, but without credentials: with them,
    # Starlette echoes whichever origin asks and allows credentials, so a page
    # an operator visits could call the management endpoints with the Basic
    # auth the browser has cached for them. The clients send `x-key` or
    # `Authorization` themselves, which CORS does not count as credentials,
    # and nothing here sets a cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
