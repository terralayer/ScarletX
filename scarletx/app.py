from __future__ import annotations

from contextlib import asynccontextmanager

from .background_tasks import AsyncioTaskProxy, BackgroundTaskRegistry
from .main import app
from .routes import application as legacy_application
from .runtime_composition import install_runtime_composition


background_task_registry = BackgroundTaskRegistry(max_tasks=128)
_legacy_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _managed_lifespan(application):
    """Bound and drain application-owned tasks while preserving legacy startup behavior."""
    original_asyncio = legacy_application.asyncio
    legacy_application.asyncio = AsyncioTaskProxy(original_asyncio, background_task_registry)
    try:
        async with _legacy_lifespan(application):
            yield
    finally:
        legacy_application.asyncio = original_asyncio
        await background_task_registry.shutdown()


install_runtime_composition(app, legacy_application)
app.router.lifespan_context = _managed_lifespan
