"""ScarletX native Usenet subsystem boundaries."""

from . import worker as worker
from .connection_budget import install_connection_budget
from .processing_capacity import install_processing_capacity
from .scheduler import _queued_job_ids, native_worker_loop

install_connection_budget(worker)
install_processing_capacity(worker)
worker._queued_job_ids = _queued_job_ids
worker.native_worker_loop = native_worker_loop

__all__ = ["native_worker_loop", "worker"]
