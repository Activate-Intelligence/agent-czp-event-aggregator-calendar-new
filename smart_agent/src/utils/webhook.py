import json
import requests
from ..utils.error_handling import error_handler
from ..config.logger import Logger
from ..utils.helper import update_task_status
from ..utils.temp_db import get_job, remove_job  # Replaced temp_data

logger = Logger()


def call_webhook_with_success(job_id: str, response: dict):
    """
    Notify the webhook for job_id of a successful status update.
    `response` should be a dict with keys: status (str), data (dict).
    """
    logger.info("Function call_webhook_with_success called", response)

    status = response.get("status")
    data = response.get("data", {})

    # 1) Update your persistent status store
    update_task_status(job_id, status, data)

    # 2) Load job from file-based store
    job = get_job(job_id)
    webhook_url = job.get("webhookUrl") if job else None

    if webhook_url:
        payload = json.dumps({"id": job_id, "status": status, "data": data})
        resp = requests.post(webhook_url, data=payload)

        # 3) Remove job from store if it's completed or failed
        if status in ("completed", "failed"):
            remove_job(job_id)

        return resp

    logger.info("Webhook URL not found for job %s", job_id)
    # Even if no webhook URL is present, ensure the job is cleaned up on failure
    if status == "failed":
        remove_job(job_id)
    return None


def call_webhook_with_error(job_id: str, error: str, code: int):
    """
    Notify the webhook (and persistent store) of a failure for job_id,
    then raise the error handler.
    """
    # Build a failure response and reuse the success-path for notification & cleanup
    response = {"status": "failed", "data": {"reason": error}}
    call_webhook_with_success(job_id, response)

    # Finally, raise so the calling code can return or log appropriately
    return error_handler(error, code)