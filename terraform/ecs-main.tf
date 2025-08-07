########################################
#            Terraform Block           #
########################################
terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    region         = "eu-west-2"
    bucket         = "533267084389-tf-state"
    key            = "aws/${var.environment}/agents/${var.service_name}-ecs"
    dynamodb_table = "533267084389-tf-lock"
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
#            Input Variables           #
########################################
variable "service_name" {
  description = "Name of the ECS service"
  type        = string
  default     = "agent-is-ai-news-aggregator"
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

variable "container_port" {
  description = "Container port (HTTP - ALB handles HTTPS termination)"
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "CPU units for the task (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Memory for the task (MB)"
  type        = number
  default     = 2048
}

variable "desired_count" {
  description = "Desired number of tasks"
  type        = number
  default     = 1
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "domain_name" {
  description = "Custom domain name for the ALB (optional)"
  type        = string
  default     = "ai-news-dev.activate.bar"
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS"
  type        = string
  default     = "arn:aws:acm:eu-west-2:533267084389:certificate/8a60fd71-f5a5-4b7a-a0ef-9b36a9c35e93"
}

########################################
#        Agent-Specific DynamoDB Table #
########################################

# Reference existing DynamoDB table (created by Lambda deployment)
data "aws_dynamodb_table" "agent_jobs" {
  name = "${var.service_name}-${var.environment}-jobs"
}

########################################
#              Networking              #
########################################
# Get default VPC
data "aws_vpc" "default" {
  default = true
}

# Get default subnets
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security group for ECS tasks
resource "aws_security_group" "ecs_tasks" {
  name        = "ai-news-${var.environment}-ecs"
  description = "Security group for ECS tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "ai-news-${var.environment}-ecs"
    Environment = var.environment
    ManagedBy   = "Terraform"
    ServiceName = var.service_name
  }
}

# Security group for ALB
resource "aws_security_group" "alb" {
  name        = "ai-news-${var.environment}-alb-sg"
  description = "Security group for Application Load Balancer"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "ai-news-${var.environment}-alb-sg"
    Environment = var.environment
    ManagedBy   = "Terraform"
    ServiceName = var.service_name
  }
}

########################################
#              Route 53                #
########################################
# Get the hosted zone for activate.bar
data "aws_route53_zone" "main" {
  name         = "activate.bar"
  private_zone = false
}

# Create A record pointing to ALB
resource "aws_route53_record" "main" {
  count   = var.domain_name != "" ? 1 : 0
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

########################################
#         Application Load Balancer    #
########################################
resource "aws_lb" "main" {
  name               = "ai-news-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets           = data.aws_subnets.default.ids

  enable_deletion_protection = false
  
  # Increase idle timeout for long-running RSS processing
  idle_timeout = 3600  # 1 hour (default is 60 seconds)

  tags = {
    Name        = "ai-news-${var.environment}-alb"
    Environment = var.environment
    ManagedBy   = "Terraform"
    ServiceName = var.service_name
  }
}

resource "aws_lb_target_group" "app" {
  name        = "ai-news-${var.environment}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"
  
  # Increase deregistration delay for long-running requests
  deregistration_delay = 3600  # 1 hour (default is 300 seconds)

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 60      # Increased from 30 for long-running tasks
    matcher             = "200"
    path                = "/status"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 10      # Increased from 5
    unhealthy_threshold = 3       # Increased from 2 for more tolerance
  }
  
  # Enable stickiness for long-running requests
  stickiness {
    enabled         = true
    type            = "lb_cookie"
    cookie_duration = 86400  # 24 hours
  }

  tags = {
    Name        = "ai-news-${var.environment}-tg"
    Environment = var.environment
    ManagedBy   = "Terraform"
    ServiceName = var.service_name
  }
}

# HTTP Listener - Redirect to HTTPS
resource "aws_lb_listener" "front_end" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS Listener - Forward to target group
resource "aws_lb_listener" "front_end_https" {
  load_balancer_arn = aws_lb.main.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

########################################
#            ECR Repository            #
########################################
resource "aws_ecr_repository" "app" {
  name                 = "${var.service_name}-${var.environment}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "${var.service_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 30 images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Delete untagged images older than 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

########################################
#         ECS Cluster & Service        #
########################################
resource "aws_ecs_cluster" "main" {
  name = "${var.service_name}-${var.environment}"

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs.name
      }
    }
  }

  tags = {
    Name        = "${var.service_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM role for ECS task execution
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.service_name}-${var.environment}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.service_name}-${var.environment}-ecs-task-execution"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# IAM role for ECS tasks
resource "aws_iam_role" "ecs_task" {
  name = "${var.service_name}-${var.environment}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.service_name}-${var.environment}-ecs-task"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Reference existing IAM policy for DynamoDB access (from Lambda deployment)
data "aws_iam_policy" "dynamodb_rw" {
  name = "${var.service_name}-${var.environment}-dynamodb-rw"
}

# Reference existing IAM policy for SSM Parameter Store access (from Lambda deployment)
data "aws_iam_policy" "ssm_parameter_read" {
  name = "${var.service_name}-${var.environment}-ssm-parameter-read"
}

resource "aws_iam_role_policy_attachment" "ecs_task_dynamodb_rw" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = data.aws_iam_policy.dynamodb_rw.arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_ssm_read" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = data.aws_iam_policy.ssm_parameter_read.arn
}

########################################
#            CloudWatch Logs          #
########################################
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.service_name}-${var.environment}"
  retention_in_days = 30

  tags = {
    Name        = "${var.service_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

########################################
#         ECS Task Definition          #
########################################
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.service_name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn           = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "${var.service_name}-${var.environment}"
      image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
      
      essential = true
      
      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "JOB_TABLE"
          value = data.aws_dynamodb_table.agent_jobs.name
        },
        {
          name  = "PARAMETER_PREFIX"
          value = "/app/${var.service_name}/${var.environment}"
        },
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.container_port}/status || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name        = "${var.service_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_ecs_service" "app" {
  name            = "${var.service_name}-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets         = data.aws_subnets.default.ids
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "${var.service_name}-${var.environment}"
    container_port   = var.container_port
  }

  # Give container 60 seconds to start before health checks begin
  health_check_grace_period_seconds = 60

  # Enable deployment circuit breaker to automatically rollback failed deployments
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.front_end, aws_lb_listener.front_end_https, aws_iam_role_policy_attachment.ecs_task_execution]

  tags = {
    Name        = "${var.service_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Note: CloudFront removed due to 60-second timeout limitation
# CloudFront cannot support long-running requests over 60 seconds
# Use the ALB URL directly for RSS processing that needs longer timeouts

########################################
#               Outputs                #
########################################
output "load_balancer_url" {
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "https://${aws_lb.main.dns_name}"
  description = "Load balancer URL (HTTPS)"
}

output "load_balancer_http_url" {
  value       = var.domain_name != "" ? "http://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
  description = "Load balancer URL (HTTP - redirects to HTTPS)"
}

output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "Raw ALB DNS name"
}

output "domain_name" {
  value       = var.domain_name
  description = "Custom domain name"
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.app.repository_url
  description = "ECR repository URL"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "ECS cluster name"
}

output "ecs_service_name" {
  value       = aws_ecs_service.app.name
  description = "ECS service name"
}

output "dynamodb_table_name" {
  value       = data.aws_dynamodb_table.agent_jobs.name
  description = "DynamoDB table name for agent jobs"
}

output "dynamodb_table_arn" {
  value       = data.aws_dynamodb_table.agent_jobs.arn
  description = "DynamoDB table ARN for agent jobs"
}

output "parameter_prefix" {
  value       = "/app/${var.service_name}/${var.environment}"
  description = "SSM Parameter prefix where all secrets are stored"
}

output "environment" {
  value       = var.environment
  description = "Deployment environment"
}

output "cloudwatch_log_group" {
  value       = aws_cloudwatch_log_group.ecs.name
  description = "CloudWatch log group name"
}

output "alternative_urls" {
  value = {
    custom_domain = var.domain_name != "" ? "https://${var.domain_name}" : "Not configured"
    alb_direct    = "https://${aws_lb.main.dns_name}"
    note          = "CloudFront not suitable due to 60-second timeout limit for long-running RSS processing"
  }
  description = "Available HTTPS endpoints for the API"
}

output "ssm_parameter_info" {
  value = {
    parameter_prefix = "/app/${var.service_name}/${var.environment}"
    description     = "All GitHub repository secrets are automatically uploaded to SSM Parameter Store under this prefix"
    access_pattern  = "ECS tasks read parameters using PARAMETER_PREFIX environment variable"
  }
}

output "dynamodb_info" {
  value = {
    table_name   = data.aws_dynamodb_table.agent_jobs.name
    table_arn    = data.aws_dynamodb_table.agent_jobs.arn
    billing_mode = data.aws_dynamodb_table.agent_jobs.billing_mode
    hash_key     = data.aws_dynamodb_table.agent_jobs.hash_key
    gsi_name     = "status-index"
    description  = "Existing DynamoDB table from Lambda deployment (shared)"
  }
}