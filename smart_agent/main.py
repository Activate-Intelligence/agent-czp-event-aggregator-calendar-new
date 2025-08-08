import os
import uvicorn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .src.routes import discover, execute, abort, status, logs
from .src.utils.cleanup import setup_cleanup_handlers

# Check if running in ECS and load parameters
is_ecs = os.environ.get('ECS_CONTAINER_METADATA_URI_V4') is not None
print(f"Environment check - ECS: {is_ecs}, LOCAL_RUN: {os.environ.get('LOCAL_RUN')}")

if is_ecs and not os.environ.get("LOCAL_RUN"):
    print("ECS environment detected - loading SSM parameters...")
    try:
        import boto3
        aws_region = os.environ.get('AWS_REGION', 'eu-west-2')
        agent_name = os.environ.get('AGENT_NAME', 'agent-czp-event-aggregator-calendar')
        environment = os.environ.get('ENVIRONMENT', 'dev')
        parameter_prefix = os.environ.get('PARAMETER_PREFIX', f'/app/{agent_name}/{environment}')
        parameter_prefix = os.path.expandvars(parameter_prefix)
        
        print(f"Loading parameters from: {parameter_prefix}")
        
        ssm_client = boto3.client('ssm', region_name=aws_region)
        paginator = ssm_client.get_paginator('get_parameters_by_path')
        parameters = {}
        
        # Load all parameters under the prefix
        for page in paginator.paginate(Path=parameter_prefix, Recursive=True, WithDecryption=True):
            for param in page['Parameters']:
                # Extract the key name (everything after the prefix)
                key = param['Name'].replace(f"{parameter_prefix}/", "")
                parameters[key] = param['Value']
                
        print(f"Found {len(parameters)} parameters in Parameter Store")
        
        # Set ALL parameters as environment variables
        for param_name, param_value in parameters.items():
            # Convert parameter name to uppercase for environment variable
            env_var_name = param_name.upper()
            os.environ[env_var_name] = param_value
            print(f"Set environment variable: {env_var_name}")
            
        print(f"Successfully loaded {len(parameters)} parameters from Parameter Store")
        print(f"ALLOW_ORIGINS after loading: {os.environ.get('ALLOW_ORIGINS', 'NOT_SET')}")
        
    except Exception as e:
        print(f"Error loading SSM parameters: {e}")
else:
    print("Skipping parameter loading - either not ECS or LOCAL_RUN is set")

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
