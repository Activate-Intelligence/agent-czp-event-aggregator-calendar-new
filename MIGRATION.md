# Migration Guide: AWS Lambda to ECS Fargate

This guide provides step-by-step instructions for converting a Lambda function into a fully working ECS instance with unlimited execution time, improved performance, and better scalability.

## 📋 Overview

**Why Migrate from Lambda to ECS?**
- ❌ **Lambda Limitations**: 15-minute execution limit insufficient for long-running tasks
- ❌ **Cold Starts**: Performance impact from container initialization
- ❌ **Memory Constraints**: Lambda memory limits may be restrictive
- ❌ **Debugging Complexity**: Limited logging and debugging capabilities

**ECS Benefits:**
- ✅ **Unlimited Execution Time**: No time constraints for long-running processes
- ✅ **Better Performance**: Container reuse eliminates cold starts
- ✅ **Enhanced Debugging**: Persistent containers and comprehensive logging
- ✅ **Flexible Scaling**: Auto-scaling based on multiple metrics
- ✅ **Cost Optimization**: Pay only for actual resource usage
- ✅ **HTTPS Support**: Native SSL/TLS with custom domains

---

## 🚀 Migration Roadmap

### Phase 1: Preparation & Analysis
1. [Analyze Current Lambda Function](#step-1-analyze-current-lambda-function)
2. [Identify Dependencies](#step-2-identify-dependencies)
3. [Plan Infrastructure Changes](#step-3-plan-infrastructure-changes)

### Phase 2: Code Adaptation
4. [Convert Lambda Handler to FastAPI](#step-4-convert-lambda-handler-to-fastapi)
5. [Create Dockerfile](#step-5-create-dockerfile)
6. [Update Configuration Management](#step-6-update-configuration-management)

### Phase 3: Infrastructure Setup
7. [Create ECS Terraform Configuration](#step-7-create-ecs-terraform-configuration)
8. [Set Up CI/CD Pipeline](#step-8-set-up-cicd-pipeline)
9. [Configure Monitoring & Logging](#step-9-configure-monitoring--logging)

### Phase 4: Deployment & Testing
10. [Deploy ECS Infrastructure](#step-10-deploy-ecs-infrastructure)
11. [Test and Validate](#step-11-test-and-validate)
12. [Performance Optimization](#step-12-performance-optimization)

---

## 📊 Pre-Migration Checklist

- [ ] Document current Lambda function's purpose and requirements
- [ ] Identify all dependencies (external APIs, databases, libraries)
- [ ] Note current resource usage (memory, execution time)
- [ ] List all environment variables and secrets
- [ ] Identify IAM permissions required
- [ ] Document API endpoints and integrations
- [ ] Plan DNS and domain requirements
- [ ] Set up testing environment

---

## 🔧 Step-by-Step Migration Guide

### Step 1: Analyze Current Lambda Function

**1.1 Document Current Function**
```bash
# Get Lambda function details
aws lambda get-function --function-name your-lambda-name

# Check current configuration
aws lambda get-function-configuration --function-name your-lambda-name

# Review recent invocations
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/your-lambda-name
```

**1.2 Create Migration Assessment**
```markdown
## Current Lambda Analysis
- **Function Name**: your-lambda-name
- **Runtime**: python3.x
- **Memory**: XXX MB
- **Timeout**: XXX seconds
- **Execution Time**: Average/Max execution time
- **Dependencies**: List of external libraries
- **IAM Role**: Current permissions
- **Triggers**: API Gateway, EventBridge, etc.
- **Environment Variables**: Count and types
```

### Step 2: Identify Dependencies

**2.1 Review requirements.txt**
```bash
# Check Python dependencies
cat requirements.txt

# Look for Lambda-specific libraries that need replacement
grep -E "(boto3|aws-lambda|lambda-runtime)" requirements.txt
```

**2.2 Identify AWS Services Used**
- DynamoDB tables
- S3 buckets  
- Parameter Store values
- Secrets Manager secrets
- Other AWS services

**2.3 Map External Integrations**
- Third-party APIs
- Databases (Neo4j, PostgreSQL, etc.)
- Message queues
- Webhook endpoints

### Step 3: Plan Infrastructure Changes

**3.1 Design ECS Architecture**
```
Lambda Function → ECS Fargate Service
    ↓                    ↓
API Gateway → Application Load Balancer
    ↓                    ↓
IAM Role    → ECS Task Role + Execution Role
    ↓                    ↓
CloudWatch  → CloudWatch + Container Insights
```

**3.2 Plan Networking**
- VPC and subnet requirements
- Security groups configuration
- Load balancer setup
- Custom domain and SSL certificate

### Step 4: Convert Lambda Handler to FastAPI

**4.1 Create FastAPI Application Structure**

Create `smart_agent/main.py`:
```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Check if running in ECS and load parameters
is_ecs = os.environ.get('ECS_CONTAINER_METADATA_URI_V4') is not None

if is_ecs and not os.environ.get("LOCAL_RUN"):
    print("ECS environment detected - loading SSM parameters...")
    try:
        import boto3
        aws_region = os.environ.get('AWS_REGION', 'eu-west-2')
        agent_name = os.environ.get('AGENT_NAME', 'your-agent-name')
        environment = os.environ.get('ENVIRONMENT', 'dev')
        parameter_prefix = os.environ.get('PARAMETER_PREFIX', f'/app/{agent_name}/{environment}')
        
        ssm_client = boto3.client('ssm', region_name=aws_region)
        paginator = ssm_client.get_paginator('get_parameters_by_path')
        parameters = {}
        
        for page in paginator.paginate(Path=parameter_prefix, Recursive=True, WithDecryption=True):
            for param in page['Parameters']:
                key = param['Name'].replace(f"{parameter_prefix}/", "")
                parameters[key] = param['Value']
        
        # Set ALL parameters as environment variables
        for param_name, param_value in parameters.items():
            env_var_name = param_name.upper()
            os.environ[env_var_name] = param_value
            
    except Exception as e:
        print(f"Error loading SSM parameters: {e}")

# Load .env for local development
load_dotenv()

# Create FastAPI app
app = FastAPI(title="Your Agent API", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOW_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint (required for ECS)
@app.get("/status")
async def health_check():
    return {"status": "healthy", "service": "your-agent"}

# Convert your Lambda handler logic
@app.post("/execute")
async def execute_task(request: dict):
    # Your existing Lambda function logic here
    # Replace lambda_handler(event, context) with this endpoint
    try:
        result = your_main_logic(request)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**4.2 Create Route Handlers**

Create `smart_agent/src/routes/` directory with individual route files:

`smart_agent/src/routes/discover.py`:
```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/discover")
async def discover():
    return {
        "agent_name": "your-agent-name",
        "capabilities": ["capability1", "capability2"],
        "version": "1.0.0"
    }
```

### Step 5: Create Dockerfile

**5.1 Create Dockerfile**
```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including curl for health checks
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY smart_agent/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY smart_agent/ ./smart_agent/
COPY lambda_handler.py .

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/status || exit 1

# Start the FastAPI application
CMD ["python", "-m", "uvicorn", "smart_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**5.2 Test Docker Build Locally**
```bash
# Build image
docker build -t your-agent-name .

# Test locally
docker run -p 8000:8000 \
  -e LOCAL_RUN=true \
  -e OPENAI_API_KEY=your_key \
  your-agent-name

# Test health check
curl http://localhost:8000/status
```

### Step 6: Update Configuration Management

**6.1 Create Configuration Loader**

Update `lambda_handler.py` to work with both Lambda and ECS:
```python
import os
import boto3

def load_parameter_store_config():
    """Load configuration from AWS Parameter Store"""
    try:
        aws_region = os.environ.get('AWS_REGION', 'eu-west-2')
        agent_name = os.environ.get('AGENT_NAME', 'your-agent-name')
        environment = os.environ.get('ENVIRONMENT', 'dev')
        parameter_prefix = f'/app/{agent_name}/{environment}'
        
        ssm_client = boto3.client('ssm', region_name=aws_region)
        paginator = ssm_client.get_paginator('get_parameters_by_path')
        
        for page in paginator.paginate(Path=parameter_prefix, Recursive=True, WithDecryption=True):
            for param in page['Parameters']:
                key = param['Name'].replace(f"{parameter_prefix}/", "")
                os.environ[key.upper()] = param['Value']
        
        return True
    except Exception as e:
        print(f"Error loading parameters: {e}")
        return False

# Legacy Lambda handler for backward compatibility
def lambda_handler(event, context):
    load_parameter_store_config()
    # Your existing Lambda logic here
    pass
```

### Step 7: Create ECS Terraform Configuration

**7.1 Create terraform/ecs-main.tf**

```hcl
########################################
#            Terraform Block           #
########################################
terraform {
  required_version = ">= 1.5.0"
  
  backend "s3" {
    region         = "eu-west-2"
    bucket         = "your-tf-state-bucket"
    key            = "aws/${var.environment}/agents/${var.service_name}-ecs"
    dynamodb_table = "your-tf-lock-table"
    encrypt        = true
  }
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

########################################
#            Variables                 #
########################################
variable "service_name" {
  description = "Name of the ECS service"
  type        = string
  default     = "your-agent-name"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-2"
}

variable "environment" {
  description = "Environment (dev/prod)"
  type        = string
  default     = "dev"
}

variable "domain_name" {
  description = "Custom domain name"
  type        = string
  default     = "your-agent.activate.bar"
}

variable "certificate_arn" {
  description = "ACM certificate ARN"
  type        = string
  default     = "arn:aws:acm:eu-west-2:123456789012:certificate/your-cert-id"
}

########################################
#        ECS Cluster & Service         #
########################################
resource "aws_ecs_cluster" "main" {
  name = "${var.service_name}-${var.environment}"
  
  tags = {
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_ecs_service" "app" {
  name            = "${var.service_name}-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  
  network_configuration {
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets         = data.aws_subnets.default.ids
    assign_public_ip = true
  }
  
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "${var.service_name}-${var.environment}"
    container_port   = 8000
  }
  
  health_check_grace_period_seconds = 60
  
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  
  depends_on = [aws_lb_listener.https]
}

# Add more resources for ALB, security groups, etc.
# (See the complete example in the actual terraform/ecs-main.tf file)
```

### Step 8: Set Up CI/CD Pipeline

**8.1 Create GitHub Actions Workflow**

Create `.github/workflows/deploy-ecs.yml`:
```yaml
name: Deploy to ECS

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v4
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: eu-west-2
    
    - name: Upload secrets to SSM Parameter Store
      run: |
        for secret in $(echo '${{ toJson(secrets) }}' | jq -r 'keys[]'); do
          if [[ "$secret" != "AWS_ACCESS_KEY_ID" && "$secret" != "AWS_SECRET_ACCESS_KEY" ]]; then
            value=$(echo '${{ toJson(secrets) }}' | jq -r --arg key "$secret" '.[$key]')
            aws ssm put-parameter \
              --name "/app/your-agent-name/dev/$secret" \
              --value "$value" \
              --type "SecureString" \
              --overwrite \
              --region eu-west-2
          fi
        done
    
    - name: Login to Amazon ECR
      run: |
        aws ecr get-login-password --region eu-west-2 | \
        docker login --username AWS --password-stdin \
        ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.eu-west-2.amazonaws.com
    
    - name: Build and push Docker image
      run: |
        docker build -t your-agent-name-dev .
        docker tag your-agent-name-dev:latest \
          ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.eu-west-2.amazonaws.com/your-agent-name-dev:latest
        docker push ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.eu-west-2.amazonaws.com/your-agent-name-dev:latest
    
    - name: Deploy to ECS
      run: |
        aws ecs update-service \
          --cluster your-agent-name-dev \
          --service your-agent-name-dev \
          --force-new-deployment \
          --region eu-west-2
```

### Step 9: Configure Monitoring & Logging

**9.1 Set Up CloudWatch Logs**
```hcl
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.service_name}-${var.environment}"
  retention_in_days = 30
  
  tags = {
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}
```

**9.2 Configure Container Logging**
```hcl
# In task definition
logConfiguration = {
  logDriver = "awslogs"
  options = {
    awslogs-group         = aws_cloudwatch_log_group.ecs.name
    awslogs-region        = var.aws_region
    awslogs-stream-prefix = "ecs"
  }
}
```

### Step 10: Deploy ECS Infrastructure

**10.1 Apply Terraform Configuration**
```bash
cd terraform

# Initialize Terraform
terraform init

# Plan deployment
terraform plan -var="environment=dev"

# Apply configuration
terraform apply -var="environment=dev"

# Get outputs
terraform output
```

**10.2 Verify Deployment**
```bash
# Check ECS service
aws ecs describe-services \
  --cluster your-agent-name-dev \
  --services your-agent-name-dev

# Check ALB health
aws elbv2 describe-target-health \
  --target-group-arn $(terraform output -raw target_group_arn)

# Test endpoint
curl -f https://your-agent.activate.bar/status
```

### Step 11: Test and Validate

**11.1 Functional Testing**
```bash
# Test health endpoint
curl https://your-agent.activate.bar/status

# Test main functionality
curl -X POST https://your-agent.activate.bar/execute \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# Test API documentation
curl https://your-agent.activate.bar/docs
```

**11.2 Performance Testing**
```bash
# Load testing with ab
ab -n 100 -c 10 https://your-agent.activate.bar/status

# Monitor resource usage
aws ecs describe-services \
  --cluster your-agent-name-dev \
  --services your-agent-name-dev \
  --query 'services[0].deployments[0]'
```

**11.3 Integration Testing**
- Test all API endpoints
- Verify database connections
- Check external API integrations
- Validate webhook functionality

### Step 12: Performance Optimization

**12.1 Optimize Container Resources**
```hcl
resource "aws_ecs_task_definition" "app" {
  cpu    = 1024  # Adjust based on load testing
  memory = 2048  # Adjust based on memory usage
  
  # Enable container insights
  container_definitions = jsonencode([{
    # ... other config
    
    # Resource limits
    memory = 2048
    memoryReservation = 1024
    
    # Health check optimization
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8000/status || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}
```

**12.2 Optimize Load Balancer**
```hcl
resource "aws_lb" "main" {
  # Optimize for long-running requests
  idle_timeout = 3600  # 1 hour
  
  # Enable deletion protection in production
  enable_deletion_protection = var.environment == "prod"
}

resource "aws_lb_target_group" "app" {
  # Optimize health checks
  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 60
    timeout             = 10
    unhealthy_threshold = 3
    path                = "/status"
  }
  
  # Enable session stickiness for long requests
  stickiness {
    enabled         = true
    type            = "lb_cookie"
    cookie_duration = 86400
  }
}
```

---

## 🚨 Common Migration Challenges & Solutions

### Challenge 1: Lambda-Specific Libraries
**Problem**: Code uses aws-lambda-powertools or similar Lambda-specific libraries
**Solution**: Replace with FastAPI equivalents
```python
# Before (Lambda)
from aws_lambda_powertools import Logger
logger = Logger()

# After (ECS)
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

### Challenge 2: Event/Context Parameters
**Problem**: Lambda handler receives event and context parameters
**Solution**: Convert to FastAPI request/response model
```python
# Before (Lambda)
def lambda_handler(event, context):
    body = json.loads(event['body'])
    return {
        'statusCode': 200,
        'body': json.dumps(response)
    }

# After (ECS)
@app.post("/execute")
async def execute(request: dict):
    # Direct access to request data
    return {"success": True, "data": response}
```

### Challenge 3: Cold Starts
**Problem**: Lambda cold starts affecting performance
**Solution**: ECS containers stay warm, but optimize startup time
```python
# Lazy load expensive resources
@lru_cache(maxsize=1)
def get_openai_client():
    return OpenAI(api_key=os.environ['OPENAI_API_KEY'])
```

### Challenge 4: Environment Variable Loading
**Problem**: Different environment loading between Lambda and ECS
**Solution**: Implement environment detection
```python
def is_running_in_ecs():
    return os.environ.get('ECS_CONTAINER_METADATA_URI_V4') is not None

def load_config():
    if is_running_in_ecs():
        load_ssm_parameters()
    else:
        load_dotenv()  # For local development
```

### Challenge 5: Timeout Issues
**Problem**: Long-running processes hitting ALB timeout
**Solution**: Configure proper timeouts and implement async processing
```hcl
# In Terraform - increase ALB timeout
resource "aws_lb" "main" {
  idle_timeout = 3600  # 1 hour
}

# Or implement async job processing
@app.post("/execute")
async def execute_async(request: dict):
    job_id = str(uuid.uuid4())
    # Start background task
    asyncio.create_task(process_job(job_id, request))
    return {"job_id": job_id, "status": "started"}
```

---

## ✅ Post-Migration Checklist

### Functional Verification
- [ ] All API endpoints working correctly
- [ ] Health checks passing
- [ ] Database connections established  
- [ ] External API integrations functional
- [ ] Error handling working as expected
- [ ] Logging and monitoring operational

### Performance Verification
- [ ] Response times acceptable
- [ ] Memory usage within limits
- [ ] CPU utilization appropriate
- [ ] Auto-scaling functioning correctly
- [ ] Load balancer distributing traffic properly

### Security Verification
- [ ] HTTPS working with valid certificate
- [ ] IAM permissions follow least privilege
- [ ] Secrets loaded from Parameter Store
- [ ] Security groups properly configured
- [ ] Container running as non-root user

### Operational Verification
- [ ] CI/CD pipeline deploying successfully  
- [ ] CloudWatch logs capturing application logs
- [ ] Alerts and monitoring configured
- [ ] Backup and recovery procedures documented
- [ ] Runbooks updated for ECS operations

---

## 📈 Success Metrics

Track these metrics to measure migration success:

| Metric | Lambda (Before) | ECS (After) | Improvement |
|--------|----------------|-------------|-------------|
| **Max Execution Time** | 15 minutes | Unlimited | ∞ |
| **Cold Start Time** | 2-5 seconds | None | 100% |
| **Memory Usage** | Fixed allocation | Dynamic | Variable |
| **Cost per Request** | Per invocation | Per hour | Depends on usage |
| **Debugging Ease** | Limited | Full access | Much better |
| **Deployment Speed** | Fast (30s) | Medium (5-10min) | Trade-off |

---

## 🎯 Best Practices Summary

1. **Start Small**: Migrate a simple function first to understand the process
2. **Test Thoroughly**: Comprehensive testing before production deployment  
3. **Monitor Closely**: Set up alerting and monitoring from day one
4. **Document Everything**: Keep detailed records of changes and configurations
5. **Plan Rollback**: Always have a rollback plan ready
6. **Security First**: Follow AWS security best practices throughout
7. **Cost Monitoring**: Track costs during and after migration
8. **Performance Baseline**: Establish performance baselines before migration

---

## 📞 Support and Resources

### AWS Documentation
- [ECS Developer Guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/)
- [Fargate User Guide](https://docs.aws.amazon.com/AmazonECS/latest/userguide/)
- [Application Load Balancer Guide](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/)

### Migration Tools
- [AWS Application Discovery Service](https://aws.amazon.com/application-discovery/)
- [AWS Migration Hub](https://aws.amazon.com/migration-hub/)
- [Container Migration Tools](https://aws.amazon.com/containers/migration-tools/)

### Community Support
- [AWS re:Post](https://repost.aws/)
- [AWS Containers Roadmap](https://github.com/aws/containers-roadmap)
- [ECS Community](https://github.com/aws/amazon-ecs)

---

**Migration Complete!** 🎉

Your Lambda function has been successfully converted to a production-ready ECS deployment with unlimited execution time, better performance, and enhanced operational capabilities.