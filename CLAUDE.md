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

### ECS Deployment (Current - Production Ready)
```bash
# Build Docker image
docker build -t agent-czp-event-aggregator-calendar .

# Run locally with Docker
docker run -p 8000:8000 agent-czp-event-aggregator-calendar

# Deploy to ECS (automatic via GitHub Actions)
git push origin main  # for dev environment
git push origin prod-release  # for prod environment

# Manual ECS operations
aws ecs update-service --cluster agent-czp-event-aggregator-calendar-dev --service agent-czp-event-aggregator-calendar-dev --force-new-deployment

# Check deployment status
aws ecs describe-services --cluster agent-czp-event-aggregator-calendar-dev --services agent-czp-event-aggregator-calendar-dev
```

### Current Deployment Status
- **Load Balancer URL**: https://czp-event-aggregator-calendar.activate.bar
- **API Documentation**: https://czp-event-aggregator-calendar.activate.bar/docs  
- **Health Check**: https://czp-event-aggregator-calendar.activate.bar/status
- **Event Processing**: POST to `/execute` endpoint

### Legacy Lambda Packaging
```bash
# Package for Lambda deployment (legacy)
python scripts/package-lambda.py

# Verify installation
python -c "import uvicorn, fastapi; print('✓ FastAPI and Uvicorn ready')"
```

## Architecture Overview

This is a **CZP Parliamentary Calendar Event Aggregator** built with the oneForAll blueprint framework, **successfully deployed on AWS ECS** with unlimited execution time for Parliamentary calendar processing. The project processes Italian Parliamentary events from Camera and Senato sources, enriches them with OpenAI, and stores them in Neo4j.

### 🚀 **Current Status: Production Ready on ECS**
- ✅ **Deployed & Running**: https://czp-event-aggregator-calendar.activate.bar
- ✅ **Unlimited Execution Time**: No 15-minute Lambda limitations
- ✅ **Parliamentary Event Processing**: Camera and Senato calendar aggregation
- ✅ **OpenAI Integration**: Event enrichment and normalization
- ✅ **Auto-scaling**: Fargate containers with load balancer
- ✅ **High Availability**: Load balancer with health checks

### Key Components

**FastAPI Application (`smart_agent/main.py`)**
- Main entry point for the FastAPI application
- Configures CORS middleware with environment-based origins
- Includes routers for: discover, execute, abort, status, logs
- Sets up cleanup handlers for graceful shutdown

**Configuration Handler (`smart_agent/lambda_handler.py`)**
- Detects ECS vs Lambda environment automatically
- Loads configuration from AWS Parameter Store or .env fallback
- Uses Mangum wrapper only for Lambda; direct FastAPI for ECS
- Handles environment variable setup and validation

**Agent Core (`smart_agent/src/agent/base_agent.py`)**
- CZP Parliamentary Calendar Event Aggregator
- Integrates with OpenAI API for event processing and analysis
- Conditional imports for heavy processing modules (ECS vs Lambda)
- Neo4j database integration for calendar event storage
- Webhook notifications for status updates
- Environment mode switching (dev/prod) for prompt handling

**Camera Events Processor (`smart_agent/src/agent/camera_events.py`)**
- Italian Camera (Lower House) parliamentary calendar scraping
- Web scraping with BeautifulSoup and proxy API integration
- Event extraction, date normalization, and OpenAI enrichment
- Neo4j integration for storing Camera events with proper relationships
- Week-based event filtering for current Parliamentary sessions

**Senato Events Processor (`smart_agent/src/agent/senato_events.py`)**
- Italian Senate (Upper House) commission calendar scraping
- Commission URL extraction and individual calendar processing
- OpenAI-powered event processing and multi-event splitting
- Neo4j batch synchronization with duplicate detection
- Target week filtering and date validation

**Configuration System**
- Agent configuration in `smart_agent/src/config/agent.json`
- Environment variables loaded from Parameter Store (AWS) or .env (local)
- Support for different agent types and configurations

**API Routes (`smart_agent/src/routes/`)**
- `/discover` - Agent capability discovery
- `/execute` - Main agent execution endpoint (Parliamentary calendar processing)
- `/abort` - Job termination
- `/status` - Job status checking
- `/logs` - Log file access

### Deployment Architecture

**ECS Deployment (Current)**
- AWS Fargate containers for scalable, long-running tasks
- Application Load Balancer with health checks
- Auto-scaling based on demand
- CloudWatch logging and monitoring
- ECR for container image storage
- Supports unlimited execution time for Parliamentary calendar processing

**Legacy Lambda Deployment**
- 15-minute execution limit (insufficient for full Parliamentary calendar processing)
- S3-based package storage in `533267084389-lambda-artifacts`
- Automatic cleanup of old deployment packages
- Kept for backward compatibility

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
- `Dockerfile` - Container configuration for ECS deployment
- `smart_agent/lambda_handler.py` - Configuration loader with ECS/Lambda detection
- `smart_agent/src/agent/base_agent.py` - Core agent logic with Parliamentary calendar processing
- `smart_agent/src/agent/camera_events.py` - Italian Camera (Lower House) event processor
- `smart_agent/src/agent/senato_events.py` - Italian Senate (Upper House) event processor
- `smart_agent/src/agent/get_prompt_from_git.py` - Dynamic prompt management system
- `smart_agent/src/agent/prompt_extract.py` - YAML prompt file processor
- `terraform/ecs-main.tf` - ECS Infrastructure as Code
- `terraform/main.tf` - Legacy Lambda Infrastructure (deprecated)
- `.github/workflows/deploy-ecs.yml` - ECS CI/CD pipeline
- `.github/workflows/deploy.yml` - Legacy Lambda CI/CD pipeline

### Environment Variables

Required for local development:
- `OPENAI_API_KEY` - OpenAI API access
- `APP_PORT` - Server port (default: 8000)
- `APP_HOST` - Server host (default: 0.0.0.0)
- `ALLOW_ORIGINS` - CORS allowed origins
- `AGENT_NAME` - Agent identifier
- `AGENT_TYPE` - Agent configuration type

ECS/Lambda-specific:
- `JOB_TABLE` - DynamoDB table name (set by Terraform)
- `PARAMETER_PREFIX` - SSM parameter path prefix
- `ENVIRONMENT` - Deployment environment (dev/prod)
- `ECS_CONTAINER_METADATA_URI_V4` - ECS detection (automatic)

Parliamentary Calendar Processing:
- Neo4j connection credentials (hardcoded in camera_events.py and senato_events.py - should be moved to environment variables)
- OpenAI processing configuration for event enrichment
- Web scraping API tokens for external proxy services

## Development Notes

### ECS vs Lambda Detection
- The application automatically detects if it's running in ECS or Lambda
- ECS provides unlimited execution time, suitable for Parliamentary calendar processing workloads
- Lambda is limited to 15 minutes, kept for backward compatibility
- Heavy processing modules (BeautifulSoup, Parliamentary scrapers) are conditionally imported

### Parliamentary Calendar Processing
- **Camera Events**: Web scraping of Italian Camera parliamentary calendar with proxy API integration
- **Senato Events**: Commission-by-commission calendar extraction from Senate website  
- **OpenAI Integration**: Event enrichment, normalization, and multi-event splitting
- **Neo4j Storage**: Graph database integration with proper Calendar → Date → Source → Event relationships
- **Week Filtering**: Target week-based event filtering for current Parliamentary sessions

### Configuration Management
- Environment mode switching for different behaviors in dev vs prod  
- Prompt files are downloaded dynamically in dev mode, static in prod mode
- All configuration is centralized through Parameter Store in AWS environments
- Local development uses .env files as fallback

### Security and Best Practices
- Neo4j credentials should be moved from hardcoded values to environment variables
- OpenAI API keys exposed in code should be moved to environment variables
- Comprehensive error handling and webhook notifications
- Cleanup handlers ensure graceful shutdown and resource cleanup
- Container security with non-root user in Dockerfile
- All secrets managed through AWS SSM Parameter Store with encryption

### Performance & Scalability
- **Parliamentary Calendar Processing**: Sequential processing of Camera and Senato sources
- **OpenAI Integration**: Event-by-event processing with retry logic and rate limiting
- **Neo4j Batch Operations**: Batch synchronization with duplicate detection
- **Auto-scaling**: ECS Fargate automatically scales based on demand
- **Resource Efficiency**: Pay only for actual usage with Fargate pricing

### Monitoring & Troubleshooting
- **CloudWatch Logs**: `/ecs/agent-czp-event-aggregator-calendar-dev`
- **Health Checks**: Load balancer monitors container health
- **DynamoDB Metrics**: Job state tracking and performance monitoring
- **ECS Service Events**: Deployment and scaling event logs
- **Neo4j Database**: Parliamentary calendar event storage and relationship monitoring

```bash
# Monitor logs
aws logs tail /ecs/agent-czp-event-aggregator-calendar-dev --follow

# Check service health  
curl https://czp-event-aggregator-calendar.activate.bar/status

# View ECS service events
aws ecs describe-services --cluster agent-czp-event-aggregator-calendar-dev --services agent-czp-event-aggregator-calendar-dev --query "services[0].events[0:5]"

# Test Parliamentary calendar processing
curl -X POST https://czp-event-aggregator-calendar.activate.bar/execute
```