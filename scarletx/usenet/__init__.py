"""ScarletX native Usenet subsystem boundaries."""

# Keep the large downloader implementation stable while the scheduling policy
# evolves independently. Importing the package installs the bounded scene-job
# scheduler on the worker module, so existing public imports remain compatible.
from . import worker as worker
from .scheduler import native_worker_loop

worker.native_worker_loop = native_worker_loop

__all__ = ["native_worker_loop", "worker"]
