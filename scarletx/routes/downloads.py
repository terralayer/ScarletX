from __future__ import annotations

from fastapi import APIRouter
from fastapi.routing import APIRoute

"""Download queue, activity, history, and job routes."""

PREFIXES = ('/api/activity', '/api/downloads', '/api/history', '/api/jobs')
router = APIRouter()


def adopt_routes(app) -> None:
    if router.routes:
        return
    selected = [
        route for route in app.router.routes
        if isinstance(route, APIRoute)
        and any(route.path.startswith(prefix) for prefix in PREFIXES)
    ]
    if not selected:
        return
    # Keep the application's registered route objects untouched. The focused
    # router is an ownership/introspection view over those exact objects, so paths,
    # methods, dependencies, names, middleware behavior, and OpenAPI stay identical.
    router.routes.extend(selected)
