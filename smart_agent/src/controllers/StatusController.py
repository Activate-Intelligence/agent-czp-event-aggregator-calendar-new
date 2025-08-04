import os
from ..utils.temp_db import get_job, list_active_jobs
from ..utils.webhook import call_webhook_with_success



class StatusController:

    @classmethod
    def get_status(self, request_id: str) -> dict:
        """
        Look up the status of a task by its request_id.
        """
        job = get_job(request_id)

        if job:
            return {
                'id': request_id,
                'status': job.get('status', 'inprogress'),
                'data': job.get('data', {})
            }
        else:
            return {
                'id': request_id,
                'status': 'not_found',
                'data': {
                    'info': (
                        "The specified task is not recognized or found in our system. "
                        "It may have been cleared due to a system restart, expired, or never existed."
                    )
                }
            }

    def can_execute(self):
        """
        Checks whether the agent can accept one more job.
        Returns a dict with 'status': 'available' or 'inprogress'.
        """
        limit = int(os.getenv('AGENT_EXECUTE_LIMIT', 1))

        # Clean up any stale or completed jobs before counting
        try:
            from ..utils.temp_db import cleanup_stale_jobs
            # Remove jobs older than 15 minutes before capacity check
            cleanup_stale_jobs(max_age_seconds=15 * 60)
        except Exception:
            pass

        active_jobs = list_active_jobs(status_filter="inprogress")

        if len(active_jobs) < limit:
            return {'status': 'available'}

        return {
            'status': 'inprogress',
            'data': {
                'info': 'Agent is busy. Please try again later.'
            }
        }
