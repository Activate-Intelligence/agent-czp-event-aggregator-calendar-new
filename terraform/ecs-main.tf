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
  description = "Container port"
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

########################################
#        Agent-Specific DynamoDB Table #
########################################
resource "aws_dynamodb_table" "agent_jobs" {
  name           = "${var.service_name}-${var.environment}-jobs"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "id"

  attribute {
    name = "id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  # Global Secondary Index for status queries
  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    projection_type = "ALL"
  }

  tags = {
    Name        = "${var.service_name}-${var.environment}-jobs"
    Environment = var.environment
    ManagedBy   = "Terraform"
    ServiceName = var.service_name
  }
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
#         Application Load Balancer    #
########################################
resource "aws_lb" "main" {
  name               = "ai-news-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets           = data.aws_subnets.default.ids

  enable_deletion_protection = false

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

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/status"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 2
  }

  tags = {
    Name        = "ai-news-${var.environment}-tg"
    Environment = var.environment
    ManagedBy   = "Terraform"
    ServiceName = var.service_name
  }
}

resource "aws_lb_listener" "front_end" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

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

# IAM policy for DynamoDB access
resource "aws_iam_policy" "dynamodb_rw" {
  name = "${var.service_name}-${var.environment}-dynamodb-rw"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:DescribeTable"
      ],
      Resource = [
        aws_dynamodb_table.agent_jobs.arn,
        "${aws_dynamodb_table.agent_jobs.arn}/index/*"
      ]
    }]
  })

  tags = {
    Name        = "${var.service_name}-${var.environment}-dynamodb-rw"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM policy for SSM Parameter Store access
resource "aws_iam_policy" "ssm_parameter_read" {
  name = "${var.service_name}-${var.environment}-ssm-parameter-read"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Action = [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
        "ssm:DescribeParameters"
      ],
      Resource = [
        "arn:aws:ssm:${var.aws_region}:*:parameter/app/${var.service_name}/${var.environment}",
        "arn:aws:ssm:${var.aws_region}:*:parameter/app/${var.service_name}/${var.environment}/*"
      ]
    }]
  })

  tags = {
    Name        = "${var.service_name}-${var.environment}-ssm-parameter-read"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_dynamodb_rw" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.dynamodb_rw.arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_ssm_read" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ssm_parameter_read.arn
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
      image = "${aws_ecr_repository.app.repository_url}:latest"
      
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
          value = aws_dynamodb_table.agent_jobs.name
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

  depends_on = [aws_lb_listener.front_end, aws_iam_role_policy_attachment.ecs_task_execution]

  tags = {
    Name        = "${var.service_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

########################################
#               Outputs                #
########################################
output "load_balancer_url" {
  value       = "http://${aws_lb.main.dns_name}"
  description = "Load balancer URL"
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
  value       = aws_dynamodb_table.agent_jobs.name
  description = "DynamoDB table name for agent jobs"
}

output "dynamodb_table_arn" {
  value       = aws_dynamodb_table.agent_jobs.arn
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

output "ssm_parameter_info" {
  value = {
    parameter_prefix = "/app/${var.service_name}/${var.environment}"
    description     = "All GitHub repository secrets are automatically uploaded to SSM Parameter Store under this prefix"
    access_pattern  = "ECS tasks read parameters using PARAMETER_PREFIX environment variable"
  }
}

output "dynamodb_info" {
  value = {
    table_name   = aws_dynamodb_table.agent_jobs.name
    table_arn    = aws_dynamodb_table.agent_jobs.arn
    billing_mode = "PAY_PER_REQUEST"
    hash_key     = "id"
    gsi_name     = "status-index"
    description  = "Agent-specific DynamoDB table for job state management"
  }
}