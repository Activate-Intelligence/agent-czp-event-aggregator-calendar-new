# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local Development
```bash
# Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r smart_agent/requirements.txt

# Run locally
cd smart_agent
python3 main.py
# OR
uvicorn main:app --reload
```

### Testing and Packaging
```bash
# Package for Lambda deployment
python scripts/package-lambda.py

# Verify installation
python -c "import uvicorn, fastapi; print('✓ FastAPI and Uvicorn ready')"
```

## Architecture Overview

This is an AI agent built with the oneForAll blueprint framework for AWS Lambda deployment. The project follows a specific structure for S3-based deployment with agent-specific DynamoDB tables.

### Key Components

**FastAPI Application (`smart_agent/main.py`)**
- Main entry point for the FastAPI application
- Configures CORS middleware with environment-based origins
- Includes routers for: discover, execute, abort, status, logs
- Sets up cleanup handlers for graceful shutdown

**Lambda Handler (`lambda_handler.py` and `smart_agent/lambda_handler.py`)**
- Root level handler imports from smart_agent module
- Loads configuration from AWS Parameter Store or .env fallback
- Uses Mangum to wrap FastAPI app for Lambda execution
- Handles environment variable setup and validation

**Agent Core (`smart_agent/src/agent/base_agent.py`)**
- Main agent processing logic with environment mode switching (dev/prod)
- Integrates with OpenAI API for LLM functionality
- Supports prompt extraction from YAML files
- Implements webhook notifications for status updates
- Uses temporary storage in dev mode, static prompts in prod

**Configuration System**
- Agent configuration in `smart_agent/src/config/agent.json`
- Environment variables loaded from Parameter Store (Lambda) or .env (local)
- Support for multiple agent types (general, gimlet, mojito, daiquiri)

**API Routes (`smart_agent/src/routes/`)**
- `/discover` - Agent capability discovery
- `/execute` - Main agent execution endpoint
- `/abort` - Job termination
- `/status` - Job status checking
- `/logs` - Log file access

### Deployment Architecture

**S3 Deployment Strategy**
- Latest-only package storage in `533267084389-lambda-artifacts`
- Automatic cleanup of old deployment packages
- Environment-specific paths: `{agent-name}/dev/` and `{agent-name}/prod/`

**DynamoDB Integration**
- Agent-specific tables: `{agent-name}-{environment}-jobs`
- PAY_PER_REQUEST billing mode with status-index GSI
- Complete data isolation between agents and environments

**Environment Management**
- `main` branch → dev environment
- `prod*` branches → prod environment
- All GitHub secrets automatically uploaded to SSM Parameter Store
- Environment-specific IAM roles and policies

### Key Files

- `smart_agent/main.py` - FastAPI application entry point
- `lambda_handler.py` - AWS Lambda handler (root level)
- `smart_agent/lambda_handler.py` - Configuration loader and app wrapper
- `smart_agent/src/agent/base_agent.py` - Core agent logic
- `scripts/package-lambda.py` - Lambda packaging script
- `terraform/main.tf` - Infrastructure as Code
- `.github/workflows/deploy.yml` - CI/CD pipeline

### Environment Variables

Required for local development:
- `OPENAI_API_KEY` - OpenAI API access
- `APP_PORT` - Server port (default: 8000)
- `APP_HOST` - Server host (default: 0.0.0.0)
- `ALLOW_ORIGINS` - CORS allowed origins
- `AGENT_NAME` - Agent identifier
- `AGENT_TYPE` - Agent configuration type

Lambda-specific:
- `JOB_TABLE` - DynamoDB table name (set by Terraform)
- `PARAMETER_PREFIX` - SSM parameter path prefix
- `ENVIRONMENT` - Deployment environment (dev/prod)

## Development Notes

- The agent uses environment mode switching for different behaviors in dev vs prod
- Prompt files are downloaded dynamically in dev mode, static in prod mode
- All configuration is centralized through Parameter Store in Lambda
- The project includes comprehensive error handling and webhook notifications
- Cleanup handlers ensure graceful shutdown and resource cleanup