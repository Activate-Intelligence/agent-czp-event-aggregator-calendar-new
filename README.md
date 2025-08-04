# agent-is-ai-news-aggregator

This is a custom AI agent built using the oneForAll blueprint framework with optimized S3-based Lambda deployment and agent-specific DynamoDB table.

## Agent Configuration
- **Agent Name**: agent-is-ai-news-aggregator
- **Agent Type**: general
- **Repository**: agent-is-ai-news-aggregator
- **Deployment**: S3-based Lambda deployment (latest-only storage)
- **Database**: Agent-specific DynamoDB table for job state management

## Description
agent-is-ai-news-aggregator is an AI agent designed to help with various tasks using the general configuration.

## Deployment Architecture
- **S3 Bucket**: 533267084389-lambda-artifacts
- **Storage Strategy**: Latest package only (automatic cleanup)
- **Structure**: agent-is-ai-news-aggregator/dev/ and agent-is-ai-news-aggregator/prod/
- **Environment Logic**: 
  - main branch → dev environment
  - prod* branches → prod environment
- **DynamoDB**: Agent-specific table with PAY_PER_REQUEST billing

## Development Guidelines

### Prerequisites
- python3 >= 3.11.3
- fastapi >= 0.70.0
- uvicorn >= 0.15.0

### Technology Stack
- FastAPI
- Uvicorn
- Poetry
- AWS Lambda (S3 deployment)
- DynamoDB (agent-specific table)
- Terraform

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
uvicorn main:app --reload
```

## Project Structure

```
agent-is-ai-news-aggregator/
├── .github/workflows/     # GitHub Actions CI/CD (S3 deployment)
├── scripts/              # Build and deployment scripts
│   └── package-lambda.py # Lambda packaging script
├── terraform/            # Infrastructure as Code (S3-based + DynamoDB)
├── smart_agent/          # Main application code
│   ├── src/
│   │   ├── agent/        # Agent implementation
│   │   ├── config/       # Configuration files
│   │   └── controllers/  # API controllers
│   ├── main.py           # Application entry point
│   ├── requirements.txt  # Python dependencies
│   └── .env.sample       # Environment template
├── lambda_handler.py     # AWS Lambda handler (root level)
├── .env                  # Environment variables (local)
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## Deployment Information

### S3 Deployment Strategy
- **Latest-Only Storage**: Only the most recent deployment package is stored
- **Automatic Cleanup**: Old packages are automatically deleted before new uploads
- **Consistent Naming**: Uses `deployment-latest.zip` for easy identification
- **Metadata Tracking**: Includes deployment timestamp, git SHA, and environment info

### DynamoDB Strategy
- **Agent-Specific Tables**: Each agent gets its own DynamoDB table
- **Table Name**: `agent-is-ai-news-aggregator-{environment}-jobs`
- **Billing Mode**: PAY_PER_REQUEST (automatic scaling)
- **Global Secondary Index**: `status-index` for efficient status queries
- **Isolation**: Complete data isolation between agents

### S3 Structure
```
533267084389-lambda-artifacts/
├── agent-is-ai-news-aggregator/
│   ├── dev/
│   │   └── deployment-latest.zip
│   └── prod/
│       └── deployment-latest.zip
```

### DynamoDB Structure
```
agent-is-ai-news-aggregator-dev-jobs    # Development environment table
agent-is-ai-news-aggregator-prod-jobs   # Production environment table
```

### Environment Management
- **Development**: Triggered by pushes to main branch
- **Production**: Triggered by pushes to prod* branches
- **SSM Parameters**: Environment-specific parameter paths
- **Resource Isolation**: Environment-specific IAM roles, policies, and DynamoDB tables

### AWS Resources
- Lambda function with S3 deployment
- API Gateway for HTTP endpoints
- Agent-specific DynamoDB table for job state
- SSM Parameter Store for secrets
- S3 bucket for deployment artifacts

## API Documentation
Once running, visit: http://localhost:8000/docs

## Built with oneForAll Blueprint
This agent was generated using the oneForAll blueprint system with optimized S3 deployment and agent-specific DynamoDB tables.
- Blueprint Repository: https://github.com/Activate-Intelligence/oneForAll_blueprint_Lambda
- Generated on: Mon Aug  4 09:26:23 BST 2025
- S3 Deployment: Latest-only storage optimization
- DynamoDB: Agent-specific table isolation
