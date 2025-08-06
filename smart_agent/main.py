import os
import uvicorn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .src.routes import discover, execute, abort, status, logs
from .src.utils.cleanup import setup_cleanup_handlers

# Check if running in ECS and load parameters
is_ecs = os.environ.get('ECS_CONTAINER_METADATA_URI_V4') is not None
if is_ecs and not os.environ.get("LOCAL_RUN"):
    print("ECS environment detected - loading SSM parameters...")
    try:
        from .lambda_handler import load_parameter_store_config
        if load_parameter_store_config():
            print("Successfully loaded SSM parameters in ECS environment")
        else:
            print("Failed to load SSM parameters, falling back to .env")
    except Exception as e:
        print(f"Error loading SSM parameters: {e}")

# Add dot env (fallback for local development)
load_dotenv()

# Create App
app = FastAPI()

# Add CORS
origins = os.environ.get('ALLOW_ORIGINS', '*')

# App middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins.split(",") if origins and origins != '*' else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add routes
app.include_router(discover.router)
app.include_router(execute.router)
app.include_router(abort.router)
app.include_router(status.router)
app.include_router(logs.router)

# Config App
host = os.environ.get('APP_HOST', default='0.0.0.0')
port = os.environ.get('APP_PORT', default='8000')
isReload = os.environ.get('IS_RELOAD', default=True)

# Run App
if __name__ == "__main__":
    setup_cleanup_handlers()
    try:
        uvicorn.run("main:app", host=host, port=int(port), reload=bool(isReload))
    except KeyboardInterrupt:
        print("Server interrupted. Cleanup complete.")
