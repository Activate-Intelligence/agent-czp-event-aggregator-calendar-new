import os
import signal

from ..utils.temp_db import get_job, remove_job
from ..utils.error_handling import error_handler
from ..config.logger import Logger

logger = Logger()


class AbortController:
    """
    The `AbortController` class provides methods to control the execution flow and stop the execution.
    """

    @classmethod
    def execution_abort(cls, job_id: str) -> dict:
        """
        Stops the execution and returns a success message.
        """
        try:
            logger.info("AbortController.execution_abort() called for %s", job_id)
            job = get_job(job_id)

            if job and job.get('id'):
                pid = int(job['id'])
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info(f"Sent SIGTERM to PID {pid} for job {job_id}")
                except ProcessLookupError:
                    logger.warning(f"Process {pid} not found for job {job_id}")

                # Remove the job from DB
                remove_job(job_id)

                return {"result": f"Execution {job_id} stopped successfully", "status": "success"}
            else:
                return {"result": f"No running execution with id {job_id}", "status": "not_found"}

        except Exception as e:
            logger.error('Error in AbortController.execution_abort: %s', e)
            raise error_handler(e, 500)
