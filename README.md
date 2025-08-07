# agent-is-ai-news-aggregator

🚀 **Production-Ready AWS ECS Deployment** - High-performance AI News Aggregator with unlimited execution time and multithreaded RSS processing.

## 🌐 Live Endpoints

- **Production URL**: https://isp-ai-news-agg-dev.activate.bar
- **API Documentation**: https://isp-ai-news-agg-dev.activate.bar/docs
- **Health Check**: https://isp-ai-news-agg-dev.activate.bar/status
- **SSL Certificate**: Valid wildcard certificate for *.activate.bar

## Overview

A sophisticated AI-powered news aggregation system that processes multiple RSS feeds simultaneously, analyzes content using OpenAI, and stores structured data in Neo4j graph database. Originally built on AWS Lambda, now successfully migrated to ECS Fargate for unlimited execution time and enhanced performance.

### Key Features
- ⚡ **Multithreaded Processing**: 5 feed workers, 3 article workers per feed
- 🤖 **AI Analysis**: OpenAI-powered content filtering and categorization
- 🔗 **Graph Database**: Neo4j for relationship mapping and knowledge extraction
- ⏰ **Unlimited Execution**: No time constraints (unlike Lambda's 15-minute limit)
- 🔒 **Secure**: HTTPS with valid SSL, IAM roles, encrypted parameters
- 📊 **Scalable**: Auto-scaling Fargate containers with load balancing
- 🚀 **CI/CD**: Automated GitHub Actions deployment pipeline

## 🏗️ Architecture

### Current Infrastructure (ECS Fargate)

```
┌─────────────────────────────────────────────────────────────┐
│                         Route53                             │
│               (isp-ai-news-agg-dev.activate.bar)           │
└──────────────────────────┬──────────────────────────────────┘
                          │
┌──────────────────────────┴──────────────────────────────────┐
│                    Application Load Balancer                │
│                  (HTTPS with SSL Certificate)               │
│                    1-hour timeout support                   │
└──────────────────────────┬──────────────────────────────────┘
                          │
┌──────────────────────────┴──────────────────────────────────┐
│                     ECS Fargate Service                     │
│                  (Auto-scaling containers)                  │
│                    ┌──────────────────┐                     │
│                    │   Docker Image   │                     │
│                    │  (FastAPI App)   │                     │
│                    └──────────────────┘                     │
└──────────────────────────┬──────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
┌───────┴────────┐ ┌──────┴──────┐ ┌───────┴────────┐
│    DynamoDB    │ │     SSM     │ │     Neo4j      │
│  (Job State)   │ │ (Parameters)│ │ (Graph Data)   │
└────────────────┘ └─────────────┘ └────────────────┘
```

### Infrastructure Components

| Component | Details |
|-----------|---------|
| **Container Platform** | AWS ECS Fargate (1024 CPU, 2048 MB) |
| **Load Balancer** | ALB with 3600s timeout for long-running tasks |
| **Container Registry** | Amazon ECR with lifecycle policies |
| **DNS** | Route53 with custom domain |
| **Database** | DynamoDB (PAY_PER_REQUEST) |
| **Graph DB** | Neo4j Cloud |
| **Configuration** | SSM Parameter Store |
| **Monitoring** | CloudWatch Logs |
| **Security** | IAM roles, VPC security groups |

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker (for local containerized testing)
- AWS CLI configured
- OpenAI API key

### Local Development

```bash
# Clone repository
git clone https://github.com/Activate-Intelligence/agent-is-ai-news-aggregator.git
cd agent-is-ai-news-aggregator

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r smart_agent/requirements.txt

# Configure environment
cat > .env << 'EOF'
APP_PORT=8000
APP_HOST=0.0.0.0
OPENAI_API_KEY=your_openai_api_key_here
AGENT_NAME=agent-is-ai-news-aggregator
AGENT_TYPE=general
ALLOW_ORIGINS=http://localhost:3000,http://localhost:9000
EOF

# Run application
cd smart_agent
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Access endpoints
# Local: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### Docker Testing

```bash
# Build Docker image
docker build -t agent-is-ai-news-aggregator .

# Run container
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=your_key \
  -e LOCAL_RUN=true \
  agent-is-ai-news-aggregator

# Test health check
curl http://localhost:8000/status
```

## 📁 Project Structure

```
agent-is-ai-news-aggregator/
├── .github/workflows/
│   ├── deploy-ecs.yml         # Active ECS deployment pipeline
│   └── deploy.yml             # Legacy Lambda deployment (disabled)
├── terraform/
│   ├── ecs-main.tf           # ECS infrastructure definition
│   └── main.tf               # Legacy Lambda infrastructure
├── smart_agent/
│   ├── src/
│   │   ├── agent/
│   │   │   ├── base_agent.py          # Core agent logic
│   │   │   └── rss_feed_processor.py  # RSS processing engine
│   │   ├── config/
│   │   │   └── agent.json             # Agent configuration
│   │   ├── routes/                    # API endpoints
│   │   └── utils/                     # Helper functions
│   ├── main.py                        # FastAPI application
│   ├── lambda_handler.py              # Configuration loader
│   └── requirements.txt               # Python dependencies
├── Dockerfile                         # Container definition
├── MIGRATION.md                       # Lambda to ECS guide
├── CLAUDE.md                         # AI assistant docs
└── README.md                         # This file
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key for content analysis | ✅ |
| `AGENT_NAME` | Agent identifier | ✅ |
| `AGENT_TYPE` | Agent configuration type | ✅ |
| `ALLOW_ORIGINS` | CORS allowed origins | ✅ |
| `APP_PORT` | Application port (default: 8000) | ❌ |
| `APP_HOST` | Application host (default: 0.0.0.0) | ❌ |
| `JOB_TABLE` | DynamoDB table name (auto-set in ECS) | ❌ |
| `PARAMETER_PREFIX` | SSM parameter path (auto-set in ECS) | ❌ |

### SSM Parameter Store

All configuration is stored in AWS SSM Parameter Store under:
```
/app/agent-is-ai-news-aggregator/dev/
```

Parameters are automatically loaded at container startup in ECS environment.

## 📊 API Documentation

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/discover` | GET | Agent capabilities discovery |
| `/execute` | POST | Start RSS processing job |
| `/status` | GET | Health check and job status |
| `/abort` | POST | Cancel running job |
| `/logs` | GET | Retrieve job logs |
| `/docs` | GET | Interactive API documentation |

### Example: Execute RSS Processing

```bash
curl -X POST https://isp-ai-news-agg-dev.activate.bar/execute \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "feeds": ["tech", "ai", "startup"]
    }
  }'
```

## 🚨 Monitoring & Operations

### CloudWatch Logs
```bash
# View real-time logs
aws logs tail /ecs/agent-is-ai-news-aggregator-dev --follow

# Search for errors
aws logs filter-log-events \
  --log-group-name /ecs/agent-is-ai-news-aggregator-dev \
  --filter-pattern "ERROR"
```

### ECS Service Management
```bash
# Check service status
aws ecs describe-services \
  --cluster agent-is-ai-news-aggregator-dev \
  --services agent-is-ai-news-aggregator-dev

# Force new deployment
aws ecs update-service \
  --cluster agent-is-ai-news-aggregator-dev \
  --service agent-is-ai-news-aggregator-dev \
  --force-new-deployment

# Scale service
aws ecs update-service \
  --cluster agent-is-ai-news-aggregator-dev \
  --service agent-is-ai-news-aggregator-dev \
  --desired-count 2
```

### Health Monitoring
```bash
# Check ALB health
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups \
    --names ai-news-dev-tg \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

# Test endpoint
curl -f https://isp-ai-news-agg-dev.activate.bar/status
```

## 🔄 CI/CD Pipeline

### GitHub Actions Workflow

1. **Trigger**: Push to `main` branch
2. **Build**: Docker image creation
3. **Push**: Upload to Amazon ECR
4. **Deploy**: Update ECS service
5. **Verify**: Health check validation

### Manual Deployment
```bash
# Build and push Docker image
docker build -t agent-is-ai-news-aggregator .
docker tag agent-is-ai-news-aggregator:latest \
  $ECR_REPOSITORY_URL:latest
docker push $ECR_REPOSITORY_URL:latest

# Update ECS service
aws ecs update-service \
  --cluster agent-is-ai-news-aggregator-dev \
  --service agent-is-ai-news-aggregator-dev \
  --force-new-deployment
```

## 🐛 Troubleshooting

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| **504 Gateway Timeout** | ALB timeout configured for 1 hour, check if request exceeds limit |
| **SSM Parameters Not Loading** | Verify IAM role has `ssm:GetParametersByPath` permission |
| **Container Health Check Failing** | Ensure curl is installed in Docker image |
| **CORS Errors** | Check ALLOW_ORIGINS environment variable includes frontend URL |
| **Task Fails to Start** | Check CloudWatch logs for startup errors |
| **Memory Issues** | Increase task memory in Terraform (default: 2048 MB) |

### Debug Commands
```bash
# Get task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster agent-is-ai-news-aggregator-dev \
  --service-name agent-is-ai-news-aggregator-dev \
  --query 'taskArns[0]' --output text)

# Describe task details
aws ecs describe-tasks \
  --cluster agent-is-ai-news-aggregator-dev \
  --tasks $TASK_ARN

# Get container logs
aws logs get-log-events \
  --log-group-name /ecs/agent-is-ai-news-aggregator-dev \
  --log-stream-name ecs/agent-is-ai-news-aggregator-dev/${TASK_ARN##*/}
```

## 🔄 Migration from Lambda

See [MIGRATION.md](MIGRATION.md) for detailed Lambda to ECS migration guide.

### Key Improvements After Migration
- ✅ **Unlimited execution time** (was 15 minutes)
- ✅ **Better performance** with container reuse
- ✅ **Simplified debugging** with persistent logs
- ✅ **Enhanced scalability** with auto-scaling
- ✅ **Improved reliability** with health checks
- ✅ **Custom domain** with SSL certificate

## 📈 Performance Metrics

- **Processing Capacity**: 50+ articles in parallel
- **Feed Workers**: 5 concurrent RSS feeds
- **Article Workers**: 3 per feed (15 total potential)
- **Timeout Support**: Up to 1 hour per request
- **Auto-scaling**: Based on CPU/memory utilization
- **Availability**: Multi-AZ deployment

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally with Docker
5. Submit a pull request

## 📝 License

This project is part of the Activate Intelligence platform.

## 🙏 Acknowledgments

- Built with the oneForAll blueprint framework
- Powered by OpenAI for intelligent content analysis
- Neo4j for advanced graph data capabilities
- AWS for robust cloud infrastructure

---

**Last Updated**: December 2024
**Status**: ✅ Production Ready
**Endpoint**: https://isp-ai-news-agg-dev.activate.bar