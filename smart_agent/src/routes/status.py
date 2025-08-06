from fastapi import APIRouter, Query
from ..controllers.StatusController import StatusController
from ..validator.status import ApiResponse

# prefix="/discover",
router = APIRouter(tags=['Agent Status'])

@router.get('/status', response_model=ApiResponse)
def discover(id: str = Query(None, description="Task ID (optional for health check)")):
  if id is None:
    # Health check endpoint - return simple status
    return ApiResponse(
      id="health-check",
      status="healthy",
      data={"service": "agent-is-ai-news-aggregator", "message": "Agent is running"}
    )
  return StatusController.get_status(id)

