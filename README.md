# agent-is-ai-news-aggregator

🚀 **Now Running on AWS ECS!** - Successfully migrated from Lambda to ECS for unlimited execution time and improved performance.

This is a custom AI News Aggregator agent that processes RSS feeds using advanced multithreaded processing and AI-powered content analysis. Originally built with the oneForAll blueprint framework and Lambda deployment, now running on AWS ECS Fargate for enhanced scalability and unlimited execution time.

## Agent Configuration
- **Agent Name**: agent-is-ai-news-aggregator
- **Agent Type**: RSS Feed Processing with AI Analysis
- **Repository**: agent-is-ai-news-aggregator
- **Deployment**: AWS ECS Fargate with Docker containers
- **Database**: Agent-specific DynamoDB table for job state management
- **Graph Database**: Neo4j for article relationships and knowledge extraction

## 🌐 Live Instance
- **Production URL**: http://ai-news-dev-alb-1234567890.eu-west-2.elb.amazonaws.com
- **Health Check**: `/status`
- **API Documentation**: `/docs`
- **Environment**: Development (auto-deployed from main branch)

## Description
The AI News Aggregator is a sophisticated agent that:
- Processes multiple RSS feeds simultaneously using multithreaded architecture
- Analyzes article content using OpenAI API for intelligent filtering and categorization
- Stores structured data in Neo4j graph database for relationship mapping
- Supports unlimited execution time (no 15-minute Lambda limit)
- Provides comprehensive performance metrics and monitoring
- Scales automatically based on demand

## 🏗️ Current Architecture (ECS Fargate)

### Production Infrastructure
- **Container Platform**: AWS ECS Fargate
- **Load Balancer**: Application Load Balancer (ALB)
- **Container Registry**: Amazon ECR
- **Networking**: VPC with public subnets
- **Auto-scaling**: ECS Service with desired count management
- **Environment Logic**:
  - main branch → dev environment
  - prod* branches → prod environment

### Core Services
- **Database**: DynamoDB (agent-is-ai-news-aggregator-dev-jobs)
- **Graph Database**: Neo4j Cloud (ff9f9095.databases.neo4j.io)
- **Configuration**: AWS SSM Parameter Store
- **Monitoring**: CloudWatch Logs (/ecs/agent-is-ai-news-aggregator-dev)
- **Security**: IAM roles with least privilege access

### Legacy Architecture (Lambda)
*Historical reference - no longer active*
- **Previous Deployment**: S3-based Lambda deployment
- **Migration Reason**: 15-minute execution limit insufficient for RSS processing
- **S3 Bucket**: 533267084389-lambda-artifacts (legacy artifacts)
- **Migration Date**: Successfully completed ECS deployment

## Development Guidelines

### Prerequisites
- python3 >= 3.11.3
- fastapi >= 0.70.0
- uvicorn >= 0.15.0

### Technology Stack
- **Web Framework**: FastAPI with async/await support
- **ASGI Server**: Uvicorn for high-performance serving
- **Containerization**: Docker with multi-stage builds
- **Infrastructure**: AWS ECS Fargate
- **Load Balancing**: Application Load Balancer (ALB)
- **Database**: DynamoDB (agent-specific table)
- **Graph Database**: Neo4j for relationship mapping
- **AI Integration**: OpenAI API for content analysis
- **Infrastructure as Code**: Terraform
- **CI/CD**: GitHub Actions with automated deployments
- **Monitoring**: AWS CloudWatch
- **Security**: AWS IAM, SSM Parameter Store

### Setup Instructions

```bash
# Step 1: Clone this repository
git clone https://github.com/Activate-Intelligence/agent-is-ai-news-aggregator.git
cd agent-is-ai-news-aggregator

# Step 2: Create a .env file with your configuration
cat > .env << 'ENV_EOF'
APP_PORT=8000
APP_HOST=0.0.0.0
ALLOW_ORIGINS=http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar
OPENAI_API_KEY=your_openai_api_key_here
AGENT_NAME=agent-is-ai-news-aggregator
AGENT_TYPE=general
GH_TOKEN=your_github_token_here
AGENT_EXECUTE_LIMIT=1
ENV_EOF

# Step 3: Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r smart_agent/requirements.txt

# Step 4: Run the agent locally
cd smart_agent
python3 main.py
# OR
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Step 5: Access the application
# Local: http://localhost:8000
# API Docs: http://localhost:8000/docs
# Health Check: http://localhost:8000/status
```

## Project Structure

```
agent-is-ai-news-aggregator/
├── .github/workflows/     # GitHub Actions CI/CD
│   ├── deploy-ecs.yml    # ECS deployment pipeline (active)
│   └── deploy.yml        # Legacy Lambda deployment
├── terraform/            # Infrastructure as Code
│   └── ecs-main.tf       # ECS Fargate infrastructure
├── smart_agent/          # Main application code
│   ├── src/
│   │   ├── agent/        # RSS processing & AI analysis
│   │   │   ├── base_agent.py          # Core agent logic
│   │   │   ├── rss_feed_processor.py  # Multithreaded RSS processing
│   │   │   └── agent_config.py        # Agent configuration
│   │   ├── config/       # Configuration files
│   │   ├── routes/       # FastAPI route handlers
│   │   └── utils/        # Utility functions
│   ├── main.py           # FastAPI application entry point
│   ├── requirements.txt  # Python dependencies
│   └── lambda_handler.py # Configuration loader (ECS + Lambda)
├── Dockerfile            # Docker containerization
├── .env                  # Environment variables (local)
├── CLAUDE.md            # Development documentation
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## 🚀 Deployment Information

### ECS Deployment Strategy
- **Container Platform**: AWS ECS Fargate with auto-scaling
- **Image Registry**: Amazon ECR with lifecycle policies
- **Load Balancer**: Application Load Balancer with health checks
- **Zero-Downtime**: Rolling deployments with health monitoring
- **Unlimited Execution**: No time limits (unlike Lambda's 15-minute cap)

### Infrastructure Components

#### ECS Resources
- **Cluster**: agent-is-ai-news-aggregator-dev
- **Service**: agent-is-ai-news-aggregator-dev
- **Task Definition**: Fargate with 1024 CPU, 2048 MB memory
- **Container Port**: 8000
- **Health Check**: `/status` endpoint

#### Networking
- **VPC**: Default VPC with public subnets
- **Security Groups**: 
  - ALB: Allows HTTP/HTTPS (80, 443)
  - ECS Tasks: Allows traffic from ALB on port 8000
- **Load Balancer**: ai-news-dev-alb-*.eu-west-2.elb.amazonaws.com

#### Data & Storage
- **DynamoDB Table**: agent-is-ai-news-aggregator-dev-jobs
- **Billing Mode**: PAY_PER_REQUEST (automatic scaling)
- **Global Secondary Index**: status-index for efficient queries
- **Neo4j Database**: Cloud-hosted graph database for article relationships

#### Configuration Management
- **SSM Parameter Store**: `/app/agent-is-ai-news-aggregator/dev/`
- **Environment Variables**: Automatically loaded from Parameter Store
- **Secrets**: Encrypted SecureString parameters for API keys
- **GitHub Integration**: All repository secrets auto-uploaded to SSM

### Environment Management
- **Development**: Triggered by pushes to main branch
- **Production**: Triggered by pushes to prod* branches  
- **Automatic Deployment**: GitHub Actions with ECS service updates
- **Resource Isolation**: Environment-specific clusters, services, and databases

### Monitoring & Logging
- **CloudWatch Logs**: `/ecs/agent-is-ai-news-aggregator-dev`
- **Container Insights**: ECS performance metrics
- **Health Monitoring**: ALB target group health checks
- **Application Metrics**: Custom performance tracking

### Current AWS Resources (ECS)
- ECS Fargate cluster and service
- Application Load Balancer with target groups
- ECR repository for container images
- Agent-specific DynamoDB table for job state
- SSM Parameter Store for configuration
- CloudWatch Logs for monitoring
- IAM roles with least privilege access

### Legacy Resources (Lambda)
*No longer active - kept for reference*
- Lambda function (deprecated)
- API Gateway (replaced by ALB)
- S3 deployment artifacts (533267084389-lambda-artifacts)

## 📊 Performance & Features

### RSS Processing Capabilities
- **Multithreaded Processing**: 5 feed workers, 3 article workers per feed
- **Concurrent Processing**: Up to 15 simultaneous article analyses
- **AI-Powered Filtering**: OpenAI integration for intelligent content analysis
- **Graph Database Storage**: Neo4j for relationship mapping and knowledge extraction
- **Unlimited Execution Time**: No 15-minute Lambda constraints

### Performance Metrics (Recent)
- **Processing Speed**: ~50+ articles processed in parallel
- **Feed Sources**: Multiple RSS feeds simultaneously
- **Success Rate**: High reliability with comprehensive error handling
- **Scalability**: Auto-scaling based on demand

### API Documentation
- **Local Development**: http://localhost:8000/docs
- **Production API**: http://ai-news-dev-alb-*.eu-west-2.elb.amazonaws.com/docs
- **Health Check**: `/status` endpoint
- **Interactive Docs**: Swagger UI with live testing capabilities

## 🔧 Operations & Maintenance

### Monitoring Commands
```bash
# Check ECS service status
aws ecs describe-services --cluster agent-is-ai-news-aggregator-dev --services agent-is-ai-news-aggregator-dev

# View container logs
aws logs tail /ecs/agent-is-ai-news-aggregator-dev --follow

# Check load balancer health
aws elbv2 describe-target-health --target-group-arn <target-group-arn>

# View SSM parameters
aws ssm get-parameters-by-path --path /app/agent-is-ai-news-aggregator/dev/
```

### Deployment Status
- ✅ **ECS Infrastructure**: Deployed and running
- ✅ **Load Balancer**: Healthy and routing traffic  
- ✅ **Container Registry**: Images successfully pushed
- ✅ **Database**: DynamoDB table operational
- ✅ **Configuration**: SSM parameters loaded
- ✅ **CI/CD Pipeline**: GitHub Actions automated deployment

### Troubleshooting
- **Container Issues**: Check CloudWatch logs at `/ecs/agent-is-ai-news-aggregator-dev`
- **Health Check Failures**: Verify `/status` endpoint response
- **Parameter Loading**: Confirm SSM Parameter Store values
- **Network Issues**: Check security group configurations

## Built with oneForAll Blueprint
This agent was generated using the oneForAll blueprint system with optimized S3 deployment and agent-specific DynamoDB tables.
- Blueprint Repository: https://github.com/Activate-Intelligence/oneForAll_blueprint_Lambda
- Generated on: Mon Aug  4 09:26:23 BST 2025
- S3 Deployment: Latest-only storage optimization
- DynamoDB: Agent-specific table isolation
