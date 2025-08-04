from fastapi import APIRouter, Query
from ..validator.agent import ApiResponse
from ..controllers.AbortController import AbortController

router = APIRouter(tags=['Process Abort'])

@router.get('/abort', response_model=ApiResponse)
def abort_execution(job_id: str = Query(..., description="Job ID to abort")):
    return AbortController.execution_abort(job_id)
