"""ScarletX native Usenet subsystem boundaries."""

# Keep the large downloader implementation stable while scheduling and connection
# policies evolve independently. Importing this package composes both policies on
# the worker module so existing public imports remain compatible.
from . import worker as worker
from .connection_budget import install_connection_budget
from .scheduler import native_worker_loop

install_connection_budget(worker)
worker.native_worker_loop = native_worker_loop

__all__ = ["native_worker_loop", "worker"]
