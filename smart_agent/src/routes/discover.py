from fastapi import APIRouter
from ..controllers.DiscoverController import DiscoverController
from ..validator.agent import ApiResponse

# prefix="/discover",
router = APIRouter(tags=['Discover News agent'])


@router.get('/discover')
def discover():
  return DiscoverController.documentation()
