########################################
#            Terraform Block           #
########################################
terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    region         = "eu-west-2"
    bucket         = "533267084389-tf-state"
    key            = "aws/${var.environment}/agents/${var.function_name}"
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
variable "function_name" {
  description = "Name of the Lambda function"
  type        = string
}

variable "s3_bucket" {
  description = "S3 bucket containing the deployment package"
  type        = string
}

variable "s3_key" {
  description = "S3 key for the deployment package"
  type        = string
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

########################################
#        Agent-Specific DynamoDB Table #
########################################
resource "aws_dynamodb_table" "agent_jobs" {
  name           = "${var.function_name}-${var.environment}-jobs"
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
    Name        = "${var.function_name}-${var.environment}-jobs"
    Environment = var.environment
    ManagedBy   = "Terraform"
    AgentName   = var.function_name
  }
}

########################################
#        Existing Resources (Data)     #
########################################
# Look-up S3 bucket - managed by GitHub Actions
data "aws_s3_bucket" "lambda_artifacts" {
  bucket = var.s3_bucket
}

# Get the S3 object to track changes
data "aws_s3_object" "lambda_package" {
  bucket = var.s3_bucket
  key    = var.s3_key
}

########################################
#         Lambda IAM Role & Policy     #
########################################
resource "aws_iam_role" "lambda_exec" {
  name = "${var.function_name}-${var.environment}-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Action    = "sts:AssumeRole",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Name        = "${var.function_name}-${var.environment}-exec"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "dynamodb_rw" {
  name = "${var.function_name}-${var.environment}-dynamodb-rw"
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
    Name        = "${var.function_name}-${var.environment}-dynamodb-rw"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_policy" "ssm_parameter_read" {
  name = "${var.function_name}-${var.environment}-ssm-parameter-read"
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
        "arn:aws:ssm:${var.aws_region}:*:parameter/app/${var.function_name}/${var.environment}",
        "arn:aws:ssm:${var.aws_region}:*:parameter/app/${var.function_name}/${var.environment}/*"
      ]
    }]
  })

  tags = {
    Name        = "${var.function_name}-${var.environment}-ssm-parameter-read"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb_rw" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.dynamodb_rw.arn
}

resource "aws_iam_role_policy_attachment" "lambda_ssm_read" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.ssm_parameter_read.arn
}

########################################
#            Lambda Function           #
########################################
resource "aws_lambda_function" "agent" {
  function_name    = "${var.function_name}-${var.environment}"
  s3_bucket        = var.s3_bucket
  s3_key           = var.s3_key
  source_code_hash = data.aws_s3_object.lambda_package.etag
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_handler.handler"
  runtime          = "python3.11"
  timeout          = 900
  memory_size      = 2048

  environment {
    variables = {
      JOB_TABLE        = aws_dynamodb_table.agent_jobs.name
      PARAMETER_PREFIX = "/app/${var.function_name}/${var.environment}"
      ENVIRONMENT      = var.environment
    }
  }

  tags = {
    Name        = "${var.function_name}-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_lambda_function_url" "agent_url" {
  function_name      = aws_lambda_function.agent.function_name
  authorization_type = "NONE"
}

########################################
#         API Gateway (optional)       #
########################################
resource "aws_apigatewayv2_api" "agent" {
  name          = "${var.function_name}-${var.environment}-api"
  protocol_type = "HTTP"
  
  tags = {
    Name        = "${var.function_name}-${var.environment}-api"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.agent.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.agent.invoke_arn
  payload_format_version = "2.0"
}

locals {
  routes = [
    { path = "/abort",          method = "GET"  },
    { path = "/discover",       method = "GET"  },
    { path = "/docs",           method = "GET"  },
    { path = "/execute",        method = "POST" },
    { path = "/log/{filename}", method = "GET"  },
    { path = "/openapi.json",   method = "ANY"  },
    { path = "/status",         method = "GET"  },
  ]
}

resource "aws_lambda_permission" "apigw" {
  for_each = { for r in local.routes : "${r.method}${r.path}" => r }

  statement_id  = "AllowAPIGatewayInvoke-${var.environment}-${replace(replace(replace(replace(replace(each.key, "/", "-"), "{", "-"), "}", "-"), " ", "-"), ".", "-")}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent.arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.agent.execution_arn}/*/${each.value.method}${each.value.path}"
}

resource "aws_apigatewayv2_route" "routes" {
  for_each  = { for r in local.routes : "${r.method} ${r.path}" => r }
  api_id    = aws_apigatewayv2_api.agent.id
  route_key = "${each.value.method} ${each.value.path}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.agent.id
  name        = "$default"
  auto_deploy = true
  
  tags = {
    Name        = "${var.function_name}-${var.environment}-stage"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

########################################
#               Outputs                #
########################################
output "api_endpoint" {
  value = aws_apigatewayv2_stage.default.invoke_url
  description = "API Gateway endpoint URL"
}

output "function_url" {
  value = aws_lambda_function_url.agent_url.function_url
  description = "Lambda function URL"
}

output "function_name" {
  value = aws_lambda_function.agent.function_name
  description = "Full Lambda function name with environment"
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.agent_jobs.name
  description = "DynamoDB table name for agent jobs"
}

output "dynamodb_table_arn" {
  value = aws_dynamodb_table.agent_jobs.arn
  description = "DynamoDB table ARN for agent jobs"
}

output "parameter_prefix" {
  value = "/app/${var.function_name}/${var.environment}"
  description = "SSM Parameter prefix where all secrets are stored"
}

output "s3_bucket" {
  value = data.aws_s3_bucket.lambda_artifacts.bucket
  description = "S3 bucket for Lambda artifacts"
}

output "s3_key" {
  value = var.s3_key
  description = "S3 key for the deployment package"
}

output "environment" {
  value = var.environment
  description = "Deployment environment"
}

output "ssm_parameter_info" {
  value = {
    parameter_prefix = "/app/${var.function_name}/${var.environment}"
    description     = "All GitHub repository secrets are automatically uploaded to SSM Parameter Store under this prefix"
    access_pattern  = "Lambda reads parameters using PARAMETER_PREFIX environment variable"
  }
}

output "dynamodb_info" {
  value = {
    table_name = aws_dynamodb_table.agent_jobs.name
    table_arn  = aws_dynamodb_table.agent_jobs.arn
    billing_mode = "PAY_PER_REQUEST"
    hash_key = "id"
    gsi_name = "status-index"
    description = "Agent-specific DynamoDB table for job state management"
  }
}
