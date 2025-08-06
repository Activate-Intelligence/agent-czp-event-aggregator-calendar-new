import os
from pathlib import Path
from mangum import Mangum

def load_parameter_store_config():
    """Load ALL configuration from AWS Parameter Store and set as environment variables."""
    try:
        import boto3
        aws_region = os.environ.get('AWS_REGION', 'eu-west-2')
        agent_name = os.environ.setdefault('AGENT_NAME', 'smart_agent')
        parameter_prefix = os.environ.get('PARAMETER_PREFIX', f'/app/{agent_name}')
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
            
        # Also set common variations/aliases for backward compatibility
        parameter_aliases = {
            'APP_PORT': ['app_port', 'port'],
            'APP_HOST': ['app_host', 'host'],
            'ALLOW_ORIGINS': ['allow_origins', 'cors_origins'],
            'OPENAI_API_KEY': ['openai_api_key', 'openai_key'],
            'AGENT_EXECUTE_LIMIT': ['agent_execute_limit', 'execute_limit'],
            'AGENT_NAME': ['agent_name', 'name'],
            'AGENT_TYPE': ['agent_type', 'type'],
            'GH_TOKEN': ['gh_token', 'github_token'],
        }
        
        # Set aliases if the main parameter exists
        for main_env_var, aliases in parameter_aliases.items():
            if main_env_var in os.environ:
                for alias in aliases:
                    alias_upper = alias.upper()
                    if alias_upper not in os.environ:
                        os.environ[alias_upper] = os.environ[main_env_var]
                        
        print(f"Successfully loaded {len(parameters)} parameters from Parameter Store")
        
        # Log available environment variables (without showing sensitive values)
        available_vars = []
        for key in os.environ.keys():
            if any(sensitive in key.upper() for sensitive in ['API_KEY', 'TOKEN', 'SECRET', 'PASSWORD']):
                available_vars.append(f"{key}=***")
            else:
                available_vars.append(f"{key}={os.environ[key]}")
        
        print("Available environment variables:")
        for var in sorted(available_vars):
            print(f"  {var}")
            
        return True
        
    except Exception as e:
        print(f"Error loading Parameter Store configuration: {str(e)}")
        return load_fallback_config()

def load_fallback_config():
    """Fallback to loading from .env file if Parameter Store fails."""
    try:
        from dotenv import load_dotenv
        
        # Try multiple .env file locations
        possible_env_files = [
            Path(__file__).resolve().parent / '.env',  # Same directory as lambda_handler
            Path(__file__).resolve().parents[1] / '.env',  # Parent directory
            Path(__file__).resolve().parents[2] / '.env',  # Root directory
            Path('.env'),  # Current working directory
        ]
        
        env_loaded = False
        for env_file in possible_env_files:
            if env_file.exists():
                load_dotenv(env_file)
                print(f'Loaded configuration from .env file: {env_file}')
                env_loaded = True
                break
                
        if not env_loaded:
            print('No .env file found in any expected location')
            # Set some sensible defaults
            default_config = {
                'APP_PORT': '8000',
                'APP_HOST': '0.0.0.0',
                'ALLOW_ORIGINS': '*',
                'AGENT_EXECUTE_LIMIT': '1',
            }
            
            for key, value in default_config.items():
                if key not in os.environ:
                    os.environ[key] = value
                    print(f'Set default: {key}={value}')
            
        return True
        
    except Exception as fallback_error:
        print(f"Fallback to .env also failed: {str(fallback_error)}")
        return False

def validate_required_config():
    """Validate that essential configuration is available."""
    required_vars = ['APP_PORT', 'APP_HOST']
    missing_vars = []
    
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"Warning: Missing required environment variables: {missing_vars}")
        return False
    
    return True

# Load configuration for both Lambda and ECS environments
if not os.environ.get("LOCAL_RUN"):
    print("Starting configuration loading...")
    
    # Check if running in ECS (has ECS metadata endpoint) or Lambda
    is_ecs = os.environ.get('ECS_CONTAINER_METADATA_URI_V4') is not None
    
    if is_ecs:
        print("Detected ECS environment")
    else:
        print("Detected Lambda environment")

    if not load_parameter_store_config():
        raise RuntimeError('Failed to load configuration from Parameter Store or .env file')

    if not validate_required_config():
        print("Warning: Some required configuration is missing, but continuing...")

    print("Configuration loaded successfully")

    # Import the FastAPI app after configuration is loaded
    try:
        from smart_agent.main import app  # noqa: E402
        print("Successfully imported FastAPI app")
    except ImportError as e:
        print(f"Import error: {e}")
        try:
            from .main import app  # noqa: E402
            print("Successfully imported FastAPI app (relative import)")
        except ImportError as e2:
            print(f"Relative import also failed: {e2}")
            raise RuntimeError(f"Failed to import FastAPI app: {e}, {e2}")

    # Create the Mangum handler only for Lambda
    if not is_ecs:
        handler = Mangum(app, lifespan='off')
        print("Lambda handler ready")
    else:
        print("ECS environment - FastAPI app ready for direct use")
