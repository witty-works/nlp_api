"""Every route of the app with the prefix it is served under.

FastAPI adds an included router to `app.routes` as one entry for the whole
router (since 0.16x), and has no public way to get from a path to the route
that serves it. The middleware needs that before routing, to tell the routes
behind a password from the rest, so the routers are recorded as they are
included and their own routes, which stay plain APIRoutes, are read from
there.
"""

from fastapi import APIRouter, FastAPI
from starlette.routing import BaseRoute


def include(app: FastAPI, router: APIRouter, prefix: str = "", **kwargs) -> None:
    """`app.include_router`, recording the router for `registered_routes`."""
    app.include_router(router, prefix=prefix, **kwargs)
    app.state.included_routers = [
        *getattr(app.state, "included_routers", []),
        (prefix, router),
    ]


def registered_routes(app: FastAPI) -> list[tuple[str, BaseRoute]]:
    """`(prefix, route)` for every route, in the order the app matches them:
    first those FastAPI adds itself (the docs, openapi.json), then those of
    each included router."""
    routes = [("", route) for route in app.routes if hasattr(route, "path")]
    for prefix, router in getattr(app.state, "included_routers", []):
        routes += [(prefix, route) for route in router.routes]
    return routes
