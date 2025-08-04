from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

router = APIRouter(tags=['Logs'])
LOGS_DIR = os.path.join(os.getcwd(), 'log')

@router.get('/log/{log_filename}')
def get_log(log_filename: str):
    file_path = os.path.join(LOGS_DIR, log_filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=404, detail="Feed file not found")

