import atexit
import signal
import sys

from .temp_db import list_active_jobs, remove_job
from ..config.logger import Logger

logger = Logger()


def _cleanup_jobs():
    """Remove any in-progress jobs from the DB."""
    active = list_active_jobs(status_filter="inprogress")
    for job in active:
        job_id = job.get("id")
        if job_id:
            logger.info("Cleaning up job %s", job_id)
            remove_job(job_id)


def _signal_handler(signum, frame):
    logger.info("Received signal %s, initiating cleanup", signum)
    _cleanup_jobs()
    sys.exit(0)


def setup_cleanup_handlers():
    """Register cleanup handlers for process exit and interrupts."""
    atexit.register(_cleanup_jobs)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
