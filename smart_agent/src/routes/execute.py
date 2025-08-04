from fastapi import APIRouter
from queue import Queue, Empty
from threading import Thread
from dotenv import load_dotenv

# Relative imports
from ..controllers.ExecuteController import ExecuteController
from ..controllers.StatusController import StatusController
from ..validator.agent import ApiResponse, AgentSchema
from ..utils.temp_db import add_job, remove_job

import os
import time

load_dotenv()

router = APIRouter(tags=['Agent execution'])


def _execute_worker(request_data: dict, result_q: Queue):
    schema = AgentSchema(**request_data)
    try:
        res = ExecuteController().execute(schema)
    except Exception as e:
        res = {"status": "error", "message": str(e)}
    finally:
        result_q.put(res)


@router.post('/execute', response_model=ApiResponse)
def execute_agent(request: AgentSchema):
    # 1. capacity check
    status = StatusController().can_execute()
    if status['status'] != 'available':
        return {'result': status}

    # 2. prepare the thread-safe queue and worker
    result_q = Queue()
    thread = Thread(target=_execute_worker, args=(request.dict(), result_q))
    thread.start()

    # 3. Register job in DynamoDB with pseudo-pid (use thread ID or os.getpid())
    job_record = {
        'id': request.id,
        'webhookUrl': request.webhookUrl,
        'pid': os.getpid(),
        'status': 'inprogress',
        'timestamp': int(time.time()),
        'isExecutionContinue': True
    }
    add_job(job_record)

    # 4. Wait for the thread to finish
    thread.join()

    # 5. Remove the job
    remove_job(request.id)

    # 6. Retrieve result from queue
    try:
        result = result_q.get_nowait()
    except Empty:
        result = {
            "status": "error",
            "message": "No response received from thread worker."
        }

    return result
