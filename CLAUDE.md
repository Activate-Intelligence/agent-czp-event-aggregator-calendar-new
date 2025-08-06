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
docker build -t agent-is-ai-news-aggregator .

# Run locally with Docker
docker run -p 8000:8000 agent-is-ai-news-aggregator

# Deploy to ECS (automatic via GitHub Actions)
git push origin main  # for dev environment
git push origin prod-release  # for prod environment

# Manual ECS operations
aws ecs update-service --cluster agent-is-ai-news-aggregator-dev --service agent-is-ai-news-aggregator-dev --force-new-deployment

# Check deployment status
aws ecs describe-services --cluster agent-is-ai-news-aggregator-dev --services agent-is-ai-news-aggregator-dev
```

### Current Deployment Status
- **Load Balancer URL**: https://ai-news-dev.activate.bar
- **API Documentation**: https://ai-news-dev.activate.bar/docs  
- **Health Check**: https://ai-news-dev.activate.bar/status
- **RSS Processing**: POST to `/execute` endpoint

### Legacy Lambda Packaging
```bash
# Package for Lambda deployment (legacy)
python scripts/package-lambda.py

# Verify installation
python -c "import uvicorn, fastapi; print('✓ FastAPI and Uvicorn ready')"
```

## Architecture Overview

This is an AI News Aggregator built with the oneForAll blueprint framework, **successfully deployed on AWS ECS** with unlimited execution time for RSS feed processing. The project uses multithreaded RSS processing to aggregate and filter AI/technology news from multiple sources.

### 🚀 **Current Status: Production Ready on ECS**
- ✅ **Deployed & Running**: https://ai-news-dev.activate.bar
- ✅ **Unlimited Execution Time**: No 15-minute Lambda limitations
- ✅ **Multithreaded Processing**: 5 feed workers, 3 article workers per feed  
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
- AI News Aggregator with RSS feed processing
- Integrates with OpenAI API for content filtering and analysis
- Multithreaded RSS processing with configurable worker pools
- Neo4j database integration for article storage
- Webhook notifications for status updates
- Environment mode switching (dev/prod) for prompt handling

**RSS Feed Processor (`smart_agent/src/agent/rss_feed_processor.py`)**
- Multithreaded RSS feed scraping and article processing
- Support for multiple news sources (TechCrunch, BBC, The Verge, etc.)
- Content extraction with fallback strategies
- Article relevance filtering using OpenAI
- Neo4j storage with duplicate detection

**Configuration System**
- Agent configuration in `smart_agent/src/config/agent.json`
- Environment variables loaded from Parameter Store (AWS) or .env (local)
- Support for different agent types and configurations

**API Routes (`smart_agent/src/routes/`)**
- `/discover` - Agent capability discovery
- `/execute` - Main agent execution endpoint (RSS processing)
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
- Supports unlimited execution time for RSS processing

**Legacy Lambda Deployment**
- 15-minute execution limit (insufficient for full RSS processing)
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
- `smart_agent/src/agent/base_agent.py` - Core agent logic with RSS processing
- `smart_agent/src/agent/rss_feed_processor.py` - Multithreaded RSS processor
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

RSS Processing:
- Neo4j connection credentials (hardcoded in base_agent.py - should be moved to environment variables)
- Multithreading configuration for feed and article workers

## Development Notes

### ECS vs Lambda Detection
- The application automatically detects if it's running in ECS or Lambda
- ECS provides unlimited execution time, suitable for RSS processing workloads
- Lambda is limited to 15 minutes, kept for backward compatibility

### RSS Feed Processing
- Multithreaded architecture with configurable worker pools
- Feed-level parallelism (5 workers) and article-level parallelism (3 workers per feed)
- Built-in duplicate detection and content relevance filtering
- Supports both standard RSS feeds and specialized sources like TLDR

### Configuration Management
- Environment mode switching for different behaviors in dev vs prod  
- Prompt files are downloaded dynamically in dev mode, static in prod mode
- All configuration is centralized through Parameter Store in AWS environments
- Local development uses .env files as fallback

### Security and Best Practices
- Neo4j credentials should be moved from hardcoded values to environment variables
- Comprehensive error handling and webhook notifications
- Cleanup handlers ensure graceful shutdown and resource cleanup
- Container security with non-root user in Dockerfile
- All secrets managed through AWS SSM Parameter Store with encryption

### Performance & Scalability
- **Multithreaded Architecture**: 5 concurrent feed workers, 3 article workers per feed
- **Total Potential Threads**: Up to 15 concurrent article processing threads
- **Processing Speed**: Significantly faster than sequential processing
- **Auto-scaling**: ECS Fargate automatically scales based on demand
- **Resource Efficiency**: Pay only for actual usage with Fargate pricing

### Monitoring & Troubleshooting
- **CloudWatch Logs**: `/ecs/agent-is-ai-news-aggregator-dev`
- **Health Checks**: Load balancer monitors container health
- **DynamoDB Metrics**: Job state tracking and performance monitoring
- **ECS Service Events**: Deployment and scaling event logs

```bash
# Monitor logs
aws logs tail /ecs/agent-is-ai-news-aggregator-dev --follow

# Check service health  
curl https://ai-news-dev.activate.bar/status

# View ECS service events
aws ecs describe-services --cluster agent-is-ai-news-aggregator-dev --services agent-is-ai-news-aggregator-dev --query "services[0].events[0:5]"
```