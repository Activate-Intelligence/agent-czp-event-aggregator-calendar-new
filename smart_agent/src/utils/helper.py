import logging
import sys

from ..utils.temp_db import get_job, update_job_fields

logger = logging.getLogger(__name__)


def is_execution_abort(job_id: str):
    """
    Raises SystemExit if the job with job_id has been aborted.
    """
    job = get_job(job_id)
    if job and not job.get("isExecutionContinue", True):
        logger.info("Abort due to request for job %s", job_id)
        sys.exit(0)


def update_task_status(job_id: str, status: str, data=None):
    """
    Updates the status and data for the job with job_id in DynamoDB.
    """
    try:
        update_job_fields(job_id, {
            "status": status,
            "data": data or {}
        })
    except Exception as e:
        logger.error(f"Failed to update task {job_id}: {e}")
