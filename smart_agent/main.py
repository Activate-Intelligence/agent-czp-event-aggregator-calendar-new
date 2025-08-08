import os
import uvicorn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .src.routes import discover, execute, abort, status, logs
from .src.utils.cleanup import setup_cleanup_handlers

# Load ECS configuration
from . import config_loader

# ECS environment - configuration already loaded by config_loader
print(f"ALLOW_ORIGINS after loading: {os.environ.get('ALLOW_ORIGINS', 'NOT_SET')}")

# Add dot env (fallback for local development only)
if os.environ.get("LOCAL_RUN"):
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
    allowed_origins = [
        "http://localhost:3000", 
        "http://localhost:9000", 
        "https://spritz.activate.bar", 
        "https://app.dev.spritz.activate.bar", 
        "https://api.dev.spritz.activate.bar",
        "https://api.spritz.activate.bar",
        "https://*.cloudfront.net"  # Allow CloudFront distributions
    ]
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

# Run App
if __name__ == "__main__":
    setup_cleanup_handlers()
    try:
        uvicorn.run("main:app", host=host, port=int(port), reload=bool(isReload))
    except KeyboardInterrupt:
        print("Server interrupted. Cleanup complete.")
