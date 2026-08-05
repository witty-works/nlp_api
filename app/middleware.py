"""Middleware configuration for security headers and CORS."""

import secure
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


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


def setup_middleware(app: FastAPI):
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
