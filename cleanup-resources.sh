#!/bin/bash

# Cleanup script for existing AWS resources to resolve Terraform conflicts
# Run this script to clean up resources before redeployment

set -e

SERVICE_NAME="agent-czp-event-aggregator-calendar"
ENVIRONMENT="dev"
REGION="eu-west-2"

echo "🧹 Cleaning up existing AWS resources for ${SERVICE_NAME}-${ENVIRONMENT}..."

# 1. Clean up ECR repository (this will delete all images!)
echo "📦 Cleaning up ECR repository..."
ECR_REPO="${SERVICE_NAME}-${ENVIRONMENT}"
if aws ecr describe-repositories --repository-names "$ECR_REPO" --region $REGION >/dev/null 2>&1; then
    echo "Deleting ECR repository: $ECR_REPO"
    # First delete all images in the repository
    aws ecr list-images --repository-name "$ECR_REPO" --region $REGION --query 'imageIds[*]' --output json | \
    jq '.[] | select(.imageTag != null) | {imageDigest: .imageDigest}' | \
    jq -s '.' | \
    aws ecr batch-delete-image --repository-name "$ECR_REPO" --region $REGION --image-ids file:///dev/stdin || echo "No images to delete"
    
    # Delete the repository
    aws ecr delete-repository --repository-name "$ECR_REPO" --region $REGION
    echo "✅ ECR repository deleted"
else
    echo "ECR repository $ECR_REPO does not exist"
fi

# 2. Clean up IAM Role Policy Attachments first
echo "🔐 Cleaning up IAM policy attachments..."
ROLES=(
    "${SERVICE_NAME}-${ENVIRONMENT}-ecs-task-execution"
    "${SERVICE_NAME}-${ENVIRONMENT}-ecs-task"
)

for ROLE in "${ROLES[@]}"; do
    if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
        echo "Detaching policies from role: $ROLE"
        # List and detach all attached policies
        aws iam list-attached-role-policies --role-name "$ROLE" --query 'AttachedPolicies[*].PolicyArn' --output text | \
        while read POLICY_ARN; do
            if [ ! -z "$POLICY_ARN" ]; then
                echo "  Detaching policy: $POLICY_ARN"
                aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$POLICY_ARN"
            fi
        done
        
        # Delete inline policies if any
        aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[*]' --output text | \
        while read POLICY_NAME; do
            if [ ! -z "$POLICY_NAME" ]; then
                echo "  Deleting inline policy: $POLICY_NAME"
                aws iam delete-role-policy --role-name "$ROLE" --policy-name "$POLICY_NAME"
            fi
        done
    fi
done

# 3. Clean up IAM Roles
echo "🔐 Cleaning up IAM roles..."
for ROLE in "${ROLES[@]}"; do
    if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
        echo "Deleting IAM role: $ROLE"
        aws iam delete-role --role-name "$ROLE"
        echo "✅ IAM role deleted: $ROLE"
    else
        echo "IAM role $ROLE does not exist"
    fi
done

# 4. Clean up IAM Policies
echo "🔐 Cleaning up IAM policies..."
POLICIES=(
    "${SERVICE_NAME}-${ENVIRONMENT}-ecs-dynamodb-rw"
    "${SERVICE_NAME}-${ENVIRONMENT}-ecs-ssm-parameter-read"
)

for POLICY_NAME in "${POLICIES[@]}"; do
    # Get policy ARN
    POLICY_ARN=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='$POLICY_NAME'].Arn" --output text 2>/dev/null || echo "")
    
    if [ ! -z "$POLICY_ARN" ]; then
        echo "Deleting IAM policy: $POLICY_NAME ($POLICY_ARN)"
        
        # First, list all policy versions and delete non-default versions
        aws iam list-policy-versions --policy-arn "$POLICY_ARN" --query 'Versions[?!IsDefaultVersion].VersionId' --output text | \
        while read VERSION_ID; do
            if [ ! -z "$VERSION_ID" ]; then
                echo "  Deleting policy version: $VERSION_ID"
                aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$VERSION_ID"
            fi
        done
        
        # Delete the policy
        aws iam delete-policy --policy-arn "$POLICY_ARN"
        echo "✅ IAM policy deleted: $POLICY_NAME"
    else
        echo "IAM policy $POLICY_NAME does not exist"
    fi
done

echo "🎉 Cleanup completed! You can now run the Terraform deployment."
echo ""
echo "⚠️  Note: This script deleted the ECR repository and all container images."
echo "   The next deployment will rebuild and push new images."