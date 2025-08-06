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
        # Import from root level lambda_handler.py (copied to /app in Dockerfile)
        import sys
        sys.path.insert(0, '/app')
        from lambda_handler import load_parameter_store_config
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
origins = os.environ.get('ALLOW_ORIGINS')

# Configure allowed origins - never default to allowing all origins
if origins and origins.strip() and origins != '*':
    # Use the configured origins from environment/SSM
    allowed_origins = [origin.strip() for origin in origins.split(",") if origin.strip()]
    print(f"CORS configured with allowed origins: {allowed_origins}")
else:
    # Fallback to localhost only for development - more secure default
    allowed_origins = ["http://localhost:3000", "http://localhost:9000"]
    print(f"CORS using development defaults: {allowed_origins}")

# App middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
use_ssl = os.environ.get('USE_SSL', default='false').lower() == 'true'

# Run App
if __name__ == "__main__":
    setup_cleanup_handlers()
    try:
        if use_ssl:
            # Run with SSL certificate
            uvicorn.run(
                "main:app", 
                host=host, 
                port=int(port), 
                reload=bool(isReload),
                ssl_keyfile="/app/ssl/server.key",
                ssl_certfile="/app/ssl/server.crt"
            )
        else:
            # Run without SSL (default)
            uvicorn.run("main:app", host=host, port=int(port), reload=bool(isReload))
    except KeyboardInterrupt:
        print("Server interrupted. Cleanup complete.")
