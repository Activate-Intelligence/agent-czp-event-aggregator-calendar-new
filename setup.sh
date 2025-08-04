#!/bin/bash

# ====== CONFIGURATION SECTION ======
# CUSTOMIZE THESE VALUES:

# Enter your new agent name (this will be used as repository name)
AGENT_NAME="agent-is-ai-news-aggregator"

# GitHub token will be read from environment variable GH_TOKEN
# Set this in your environment: export GH_TOKEN="your_token_here"
GH_TOKEN="${GH_TOKEN}"

# Uncomment only one agent_type at a time
agent_type='general'
# agent_type='gimlet'
# agent_type='mojito'
# agent_type='daiquiri'

# ====== END CONFIGURATION SECTION ======

# Convert agent name to repository-friendly format (lowercase, replace spaces with hyphens)
REPO_NAME=$(echo "$AGENT_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/ /-/g' | sed 's/[^a-z0-9-]//g')
BLUEPRINT_REPO_URL="https://$GH_TOKEN:x-oauth-basic@github.com/Activate-Intelligence/agent-blueprint.git"
PROJECT_NAME="smart_agent"  # Keep this fixed as smart_agent
GITHUB_ORG="Activate-Intelligence"
TEMP_CLONE_DIR="blueprint_temp"

# Function to prompt for missing environment variables
prompt_missing_variables() {
    local missing_vars=("$@")
    
    echo "**"
    echo -e "\e[33mMissing required environment variables detected.\e[0m"
    echo -e "\e[33mPlease provide the following values:\e[0m"
    echo "**"
    
    for var in "${missing_vars[@]}"; do
        case $var in
            "GH_TOKEN")
                echo -e "\e[32mEnter your GitHub Personal Access Token:\e[0m"
                echo -e "\e[33m(Create one at: https://github.com/settings/tokens)\e[0m"
                echo -e "\e[33m(Required scopes: repo, workflow, write:packages)\e[0m"
                read -s -p "GH_TOKEN: " input_value
                echo ""
                if [ -n "$input_value" ]; then
                    export GH_TOKEN="$input_value"
                    GH_TOKEN="$input_value"
                    echo -e "\e[32m✓ GitHub token set\e[0m"
                else
                    echo -e "\e[31m❌ GitHub token cannot be empty\e[0m"
                    return 1
                fi
                ;;
            "OPENAI_API_KEY")
                echo -e "\e[32mEnter your OpenAI API Key:\e[0m"
                echo -e "\e[33m(Get one at: https://platform.openai.com/api-keys)\e[0m"
                read -s -p "OPENAI_API_KEY: " input_value
                echo ""
                if [ -n "$input_value" ]; then
                    export OPENAI_API_KEY="$input_value"
                    echo -e "\e[32m✓ OpenAI API key set\e[0m"
                else
                    echo -e "\e[31m❌ OpenAI API key cannot be empty\e[0m"
                    return 1
                fi
                ;;
        esac
        echo ""
    done
    
    echo -e "\e[32m✓ All required environment variables have been set\e[0m"
    echo "**"
    return 0
}

# Function to set repository secrets using GitHub API
set_repo_secrets_api() {
    echo "Setting repository secrets using GitHub API..."

    # Get repository public key for encryption
    public_key_response=$(curl -s -H "Authorization: token $GH_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/repos/$GITHUB_ORG/$REPO_NAME/actions/secrets/public-key")

    if [ $? -ne 0 ]; then
        echo -e "\e[31m❌ Failed to get repository public key\e[0m"
        return 1
    fi

    # Extract public key and key_id using Python for more reliable JSON parsing
    key_data=$(python3 -c "
import json
import sys
try:
    data = json.loads('''$public_key_response''')
    print(f\"{data['key']}|||{data['key_id']}\")
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
")

    if [[ "$key_data" == ERROR* ]]; then
        echo -e "\e[31m❌ Failed to parse public key response: $key_data\e[0m"
        echo "Response: $public_key_response"
        return 1
    fi

    PUBLIC_KEY=$(echo "$key_data" | cut -d'|' -f1)
    KEY_ID=$(echo "$key_data" | cut -d'|' -f4)

    if [ -z "$PUBLIC_KEY" ] || [ -z "$KEY_ID" ]; then
        echo -e "\e[31m❌ Failed to extract public key information\e[0m"
        echo "Key data: $key_data"
        return 1
    fi

    echo -e "\e[32m✓ Successfully retrieved repository public key\e[0m"

    # Function to encrypt and set a secret
    set_secret() {
        local secret_name=$1
        local secret_value=$2

        echo "Setting secret: $secret_name"

        # Use Python to encrypt the secret (sodium encryption)
        encrypted_value=$(python3 -c "
import base64
import sys
try:
    from nacl import encoding, public
    public_key = public.PublicKey('$PUBLIC_KEY', encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt('$secret_value'.encode('utf-8'))
    print(base64.b64encode(encrypted).decode('utf-8'))
except ImportError:
    print('ERROR: PyNaCl not installed')
    sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
")

        if [[ "$encrypted_value" == ERROR* ]]; then
            echo -e "\e[33m⚠ Encryption failed for $secret_name: $encrypted_value\e[0m"
            echo -e "\e[33m  Installing PyNaCl and retrying...\e[0m"

            # Install PyNaCl
            pip install --no-user pynacl >/dev/null 2>&1

            # Retry encryption
            encrypted_value=$(python3 -c "
import base64
import sys
try:
    from nacl import encoding, public
    public_key = public.PublicKey('$PUBLIC_KEY', encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt('$secret_value'.encode('utf-8'))
    print(base64.b64encode(encrypted).decode('utf-8'))
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
")

            if [[ "$encrypted_value" == ERROR* ]]; then
                echo -e "\e[31m❌ Failed to encrypt $secret_name after installing PyNaCl\e[0m"
                return 1
            fi
        fi

        # Set the secret using GitHub API
        response=$(curl -s -w "%{http_code}" -X PUT \
            -H "Authorization: token $GH_TOKEN" \
            -H "Accept: application/vnd.github.v3+json" \
            -H "Content-Type: application/json" \
            -d "{
                \"encrypted_value\": \"$encrypted_value\",
                \"key_id\": \"$KEY_ID\"
            }" \
            "https://api.github.com/repos/$GITHUB_ORG/$REPO_NAME/actions/secrets/$secret_name")

        http_code="${response: -3}"
        response_body="${response%???}"

        if [ "$http_code" = "201" ] || [ "$http_code" = "204" ]; then
            echo -e "\e[32m✓ Set secret: $secret_name\e[0m"
        else
            echo -e "\e[31m❌ Failed to set secret $secret_name (HTTP: $http_code)\e[0m"
            echo "Response: $response_body"
            return 1
        fi
    }

    # Set all required secrets
    echo "Setting repository secrets..."

    set_secret "APP_PORT" "${APP_PORT:-8000}"
    set_secret "APP_HOST" "${APP_HOST:-0.0.0.0}"
    set_secret "GH_TOKEN" "$GH_TOKEN"
    set_secret "ALLOW_ORIGINS" "${ALLOW_ORIGINS:-http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar}"
    set_secret "OPENAI_API_KEY" "${OPENAI_API_KEY:-Enter_Key}"
    set_secret "AGENT_NAME" "$AGENT_NAME"
    set_secret "AGENT_TYPE" "$agent_type"
    set_secret "AGENT_EXECUTE_LIMIT" "${AGENT_EXECUTE_LIMIT:-1}"

    echo -e "\e[32m✓ Repository secrets configured successfully\e[0m"
    return 0
}

# Function to set repository secrets using gh CLI (fallback)
set_repo_secrets_gh() {
    echo "Setting repository secrets using gh CLI..."

    if ! command -v gh >/dev/null 2>&1; then
        echo -e "\e[33m⚠ gh CLI not found, skipping gh CLI method\e[0m"
        return 1
    fi

    # Check if gh is authenticated
    if ! gh auth status >/dev/null 2>&1; then
        echo -e "\e[33m⚠ gh CLI not authenticated, attempting login with token\e[0m"
        echo "$GH_TOKEN" | gh auth login --with-token

        if ! gh auth status >/dev/null 2>&1; then
            echo -e "\e[31m❌ Failed to authenticate gh CLI\e[0m"
            return 1
        fi
    fi

    # Set secrets using gh CLI
    echo "$APP_PORT" | gh secret set APP_PORT -R "$GITHUB_ORG/$REPO_NAME"
    echo "$APP_HOST" | gh secret set APP_HOST -R "$GITHUB_ORG/$REPO_NAME"
    echo "$GH_TOKEN" | gh secret set GH_TOKEN -R "$GITHUB_ORG/$REPO_NAME"
    echo "$ALLOW_ORIGINS" | gh secret set ALLOW_ORIGINS -R "$GITHUB_ORG/$REPO_NAME"
    echo "$OPENAI_API_KEY" | gh secret set OPENAI_API_KEY -R "$GITHUB_ORG/$REPO_NAME"
    echo "$AGENT_NAME" | gh secret set AGENT_NAME -R "$GITHUB_ORG/$REPO_NAME"
    echo "$agent_type" | gh secret set AGENT_TYPE -R "$GITHUB_ORG/$REPO_NAME"
    echo "$AGENT_EXECUTE_LIMIT" | gh secret set AGENT_EXECUTE_LIMIT -R "$GITHUB_ORG/$REPO_NAME"

    echo -e "\e[32m✓ Repository secrets set via gh CLI\e[0m"
    return 0
}

# Function to create GitHub repository with README and set team permissions
create_github_repo_with_readme() {
    echo "Creating new private GitHub repository: $REPO_NAME in $GITHUB_ORG organization..."

    # Create repository using GitHub API (empty repository)
    response=$(curl -s -w "%{http_code}" -X POST \
        -H "Authorization: token $GH_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        -d "{
            \"name\": \"$REPO_NAME\",
            \"description\": \"$AGENT_NAME - AI Agent built with oneForAll blueprint\",
            \"private\": true,
            \"auto_init\": false
        }" \
        "https://api.github.com/orgs/$GITHUB_ORG/repos")

    # Extract HTTP status code (last 3 characters)
    http_code="${response: -3}"
    response_body="${response%???}"

    if [ "$http_code" = "201" ]; then
        echo -e "\e[32m✓ Private repository '$REPO_NAME' created successfully\e[0m"
        
        # Add team permissions after successful repository creation
        add_team_permissions
        
    elif [ "$http_code" = "422" ]; then
        if echo "$response_body" | grep -q "already exists"; then
            echo -e "\e[33m⚠ Repository '$REPO_NAME' already exists\e[0m"
            
            # Still try to add team permissions for existing repository
            add_team_permissions
        else
            echo -e "\e[31m❌ Failed to create repository: $response_body\e[0m"
            exit 1
        fi
    else
        echo -e "\e[31m❌ Failed to create repository. HTTP Code: $http_code\e[0m"
        echo -e "\e[31mResponse: $response_body\e[0m"
        exit 1
    fi

    echo -e "\e[32m✓ Private repository created/verified\e[0m"
    echo -e "\e[32m📂 Repository URL: https://github.com/$GITHUB_ORG/$REPO_NAME\e[0m"
}

# Function to add team permissions to repository
add_team_permissions() {
    echo "Adding @Activate-Intelligence/ai-dev team with admin access..."
    
    # Add ai-dev team with admin permissions
    team_response=$(curl -s -w "%{http_code}" -X PUT \
        -H "Authorization: token $GH_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        -H "Content-Type: application/json" \
        -d "{
            \"permission\": \"admin\"
        }" \
        "https://api.github.com/orgs/$GITHUB_ORG/teams/ai-dev/repos/$GITHUB_ORG/$REPO_NAME")

    # Extract HTTP status code
    team_http_code="${team_response: -3}"
    team_response_body="${team_response%???}"

    if [ "$team_http_code" = "204" ]; then
        echo -e "\e[32m✓ Successfully added @Activate-Intelligence/ai-dev team with admin access\e[0m"
    elif [ "$team_http_code" = "404" ]; then
        echo -e "\e[33m⚠ Team 'ai-dev' not found in organization. Skipping team permissions.\e[0m"
        echo -e "\e[33m  You may need to add team permissions manually at:\e[0m"
        echo -e "\e[33m  https://github.com/$GITHUB_ORG/$REPO_NAME/settings/access\e[0m"
    else
        echo -e "\e[33m⚠ Failed to add team permissions (HTTP: $team_http_code)\e[0m"
        echo -e "\e[33m  Response: $team_response_body\e[0m"
        echo -e "\e[33m  You can add team permissions manually at:\e[0m"
        echo -e "\e[33m  https://github.com/$GITHUB_ORG/$REPO_NAME/settings/access\e[0m"
    fi
}

# Function to create GitHub workflow file with S3 deployment and cleanup
create_github_workflow() {
    cat > ".github/workflows/deploy.yml" <<EOF
name: Deploy $REPO_NAME Lambda

on:
  push:
    branches: [main, 'prod**']
  pull_request:
    branches: ['prod**']

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    env:
      TF_VAR_function_name: $REPO_NAME
      TF_VAR_aws_region: eu-west-2
      S3_BUCKET: 533267084389-lambda-artifacts
      
    steps:
      - uses: actions/checkout@v4
      
      - name: Determine Environment
        id: env
        run: |
          if [[ "\${{ github.ref }}" == "refs/heads/main" ]]; then
            echo "environment=dev" >> \$GITHUB_OUTPUT
            echo "Environment: dev (main branch)"
          elif [[ "\${{ github.ref }}" == refs/heads/prod* ]]; then
            echo "environment=prod" >> \$GITHUB_OUTPUT
            echo "Environment: prod (production branch)"
          else
            echo "environment=dev" >> \$GITHUB_OUTPUT
            echo "Environment: dev (default)"
          fi
          
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install -r smart_agent/requirements.txt
          pip install mangum boto3
          
      - name: Package Lambda
        run: |
          python scripts/package-lambda.py
          
      - name: AWS credentials via OIDC
        uses: aws-actions/configure-aws-credentials@v3
        with:
          role-to-assume: arn:aws:iam::533267084389:role/github
          aws-region: eu-west-2
          
      - name: Create S3 bucket if not exists
        run: |
          echo "Checking if S3 bucket exists..."
          if aws s3api head-bucket --bucket \$S3_BUCKET 2>/dev/null; then
            echo "✓ S3 bucket \$S3_BUCKET already exists"
          else
            echo "Creating S3 bucket \$S3_BUCKET..."
            aws s3api create-bucket \\
              --bucket \$S3_BUCKET \\
              --region eu-west-2 \\
              --create-bucket-configuration LocationConstraint=eu-west-2
            
            # Enable versioning
            aws s3api put-bucket-versioning \\
              --bucket \$S3_BUCKET \\
              --versioning-configuration Status=Enabled
            
            # Enable encryption
            aws s3api put-bucket-encryption \\
              --bucket \$S3_BUCKET \\
              --server-side-encryption-configuration '{
                "Rules": [
                  {
                    "ApplyServerSideEncryptionByDefault": {
                      "SSEAlgorithm": "AES256"
                    }
                  }
                ]
              }'
            
            # Configure lifecycle policy to keep only latest version
            aws s3api put-bucket-lifecycle-configuration \\
              --bucket \$S3_BUCKET \\
              --lifecycle-configuration '{
                "Rules": [
                  {
                    "ID": "KeepLatestVersionOnly",
                    "Status": "Enabled",
                    "Filter": {},
                    "NoncurrentVersionExpiration": {
                      "NoncurrentDays": 1
                    },
                    "ExpiredObjectDeleteMarker": true
                  }
                ]
              }'
            
            echo "✓ S3 bucket \$S3_BUCKET created successfully"
          fi
          
      - name: Clean up old packages and upload latest
        id: upload
        run: |
          ENVIRONMENT=\${{ steps.env.outputs.environment }}
          S3_PREFIX="$REPO_NAME/\$ENVIRONMENT/"
          S3_KEY="\${S3_PREFIX}deployment-latest.zip"
          
          echo "Cleaning up old packages in \$S3_PREFIX..."
          
          # List and delete all existing files in the environment folder
          aws s3 ls s3://\$S3_BUCKET/\$S3_PREFIX || echo "No existing files found"
          
          # Delete all files in the environment folder
          aws s3 rm s3://\$S3_BUCKET/\$S3_PREFIX --recursive || echo "No files to delete"
          
          echo "Uploading latest Lambda package to S3..."
          aws s3 cp deployment.zip s3://\$S3_BUCKET/\$S3_KEY \\
            --metadata "deployment-timestamp=\$(date -u +%Y%m%d%H%M%S),git-sha=\${{ github.sha }},environment=\$ENVIRONMENT"
          
          echo "s3_key=\$S3_KEY" >> \$GITHUB_OUTPUT
          echo "s3_bucket=\$S3_BUCKET" >> \$GITHUB_OUTPUT
          echo "✓ Latest package uploaded to s3://\$S3_BUCKET/\$S3_KEY"
          
          # Verify upload
          aws s3 ls s3://\$S3_BUCKET/\$S3_KEY
          
      - name: Upload all secrets to SSM
        env:
          SECRETS_JSON: \${{ toJson(secrets) }}
          ENVIRONMENT: \${{ steps.env.outputs.environment }}
        run: |
          echo "Uploading all repository secrets to SSM Parameter Store..."
          
          # Function to create or update SSM parameter
          create_or_update_parameter() {
            local param_name="\$1"
            local param_value="\$2"
            local param_type="\$3"
            
            echo "Processing parameter: \$param_name"
            
            # First, try to create the parameter with tags (new parameter)
            if aws ssm put-parameter \\
              --name "\$param_name" \\
              --value "\$param_value" \\
              --type "\$param_type" \\
              --tags Key=Name,Value="$REPO_NAME-\$(basename \$param_name)" Key=Environment,Value=\$ENVIRONMENT Key=ManagedBy,Value=GitHubActions \\
              --no-overwrite \\
              2>/dev/null; then
              echo "✓ Created new parameter: \$param_name"
            else
              # Parameter exists, update it (without tags)
              if aws ssm put-parameter \\
                --name "\$param_name" \\
                --value "\$param_value" \\
                --type "\$param_type" \\
                --overwrite; then
                echo "✓ Updated existing parameter: \$param_name"
                
                # Try to add/update tags separately (ignore errors if tags already exist)
                aws ssm add-tags-to-resource \\
                  --resource-type "Parameter" \\
                  --resource-id "\$param_name" \\
                  --tags Key=Name,Value="$REPO_NAME-\$(basename \$param_name)" Key=Environment,Value=\$ENVIRONMENT Key=ManagedBy,Value=GitHubActions \\
                  2>/dev/null || echo "Note: Could not update tags for \$param_name (may already exist)"
              else
                echo "❌ Failed to create/update parameter: \$param_name"
                return 1
              fi
            fi
          }
          
          # Parse secrets and upload each one
          echo "\$SECRETS_JSON" | jq -r 'to_entries[] | select(.key != "GITHUB_TOKEN") | @base64' | while read -r entry; do
            # Decode the entry
            decoded=\$(echo \$entry | base64 --decode)
            
            # Extract key and value
            key=\$(echo \$decoded | jq -r '.key')
            value=\$(echo \$decoded | jq -r '.value')
            
            # Skip empty values
            if [ -n "\$value" ] && [ "\$value" != "null" ]; then
              # Determine parameter type based on key name
              if [[ \$key == *"API_KEY"* ]] || [[ \$key == *"TOKEN"* ]] || [[ \$key == *"SECRET"* ]] || [[ \$key == *"PASSWORD"* ]]; then
                param_type="SecureString"
              else
                param_type="String"
              fi
              
              # Create full parameter name with environment
              param_name="/app/$REPO_NAME/\$ENVIRONMENT/\$key"
              
              # Create or update the parameter
              create_or_update_parameter "\$param_name" "\$value" "\$param_type"
            else
              echo "⚠ Skipping empty secret: \$key"
            fi
          done
          
          echo "✓ All secrets processed for SSM Parameter Store"
          
      - name: Verify SSM parameters
        run: |
          ENVIRONMENT=\${{ steps.env.outputs.environment }}
          echo "Verifying uploaded parameters..."
          aws ssm describe-parameters \\
            --parameter-filters Key=Name,Values="/app/$REPO_NAME/\$ENVIRONMENT/" \\
            --query 'Parameters[].{Name:Name,Type:Type,LastModifiedDate:LastModifiedDate}' \\
            --output table
            
      - name: Set up Terraform
        uses: hashicorp/setup-terraform@v2
        with:
          terraform_wrapper: false
          
      - name: Terraform init + apply
        env:
          ENVIRONMENT: \${{ steps.env.outputs.environment }}
        run: |
          # Update terraform backend key with environment
          terraform -chdir=terraform init \\
            -backend-config="region=eu-west-2" \\
            -backend-config="bucket=533267084389-tf-state" \\
            -backend-config="key=aws/\$ENVIRONMENT/agents/$REPO_NAME" \\
            -backend-config="dynamodb_table=533267084389-tf-lock" \\
            -backend-config="encrypt=true"
            
          terraform -chdir=terraform apply -auto-approve \\
            -var="s3_bucket=\${{ steps.upload.outputs.s3_bucket }}" \\
            -var="s3_key=\${{ steps.upload.outputs.s3_key }}" \\
            -var="environment=\$ENVIRONMENT"
            
      - name: Show endpoints
        run: |
          cd terraform
          echo "::notice title=Environment::\${{ steps.env.outputs.environment }}"
          echo "::notice title=API Gateway Endpoint::\$(terraform output -raw api_endpoint)"
          echo "::notice title=Lambda Function URL::\$(terraform output -raw function_url)"
          echo "::notice title=Function Name::\$(terraform output -raw function_name)"
          echo "::notice title=DynamoDB Table::\$(terraform output -raw dynamodb_table_name)"
          echo "::notice title=S3 Package Location::s3://\${{ steps.upload.outputs.s3_bucket }}/\${{ steps.upload.outputs.s3_key }}"
          echo "::notice title=SSM Parameters::\$(aws ssm describe-parameters --parameter-filters Key=Name,Values=/app/$REPO_NAME/\${{ steps.env.outputs.environment }}/ --query 'Parameters[].Name' --output table)"
          
      - name: Clean up local artifacts
        run: |
          echo "Cleaning up local build artifacts..."
          rm -f deployment.zip
          rm -rf package/
          echo "✓ Local artifacts cleaned up"
EOF

    echo "✓ Created workflow file at .github/workflows/deploy.yml"
}

# Function to set repository secrets (tries both methods)
set_repo_secrets() {
    echo "**"
    echo -e "\e[32mConfiguring GitHub Actions repository secrets...\e[0m"
    echo "**"

    # Wait a moment for repository to be fully created
    sleep 2

    # Try GitHub API first, fallback to gh CLI
    if set_repo_secrets_api; then
        echo -e "\e[32m✓ Successfully set all repository secrets via GitHub API\e[0m"
        return 0
    else
        echo -e "\e[33m⚠ GitHub API method failed, trying gh CLI...\e[0m"
        if set_repo_secrets_gh; then
            echo -e "\e[32m✓ Successfully set all repository secrets via gh CLI\e[0m"
            return 0
        else
            echo -e "\e[31m❌ Both secret setting methods failed\e[0m"
            echo -e "\e[33m⚠ You'll need to set repository secrets manually at:\e[0m"
            echo -e "\e[33m  https://github.com/$GITHUB_ORG/$REPO_NAME/settings/secrets/actions\e[0m"
            echo -e "\e[33m  Required secrets:\e[0m"
            echo -e "\e[33m    - APP_PORT: ${APP_PORT:-8000}\e[0m"
            echo -e "\e[33m    - APP_HOST: ${APP_HOST:-0.0.0.0}\e[0m"
            echo -e "\e[33m    - GH_TOKEN: [your GitHub token]\e[0m"
            echo -e "\e[33m    - ALLOW_ORIGINS: [cors origins]\e[0m"
            echo -e "\e[33m    - OPENAI_API_KEY: [your OpenAI key]\e[0m"
            echo -e "\e[33m    - AGENT_NAME: $AGENT_NAME\e[0m"
            echo -e "\e[33m    - AGENT_TYPE: $agent_type\e[0m"
            echo -e "\e[33m    - AGENT_EXECUTE_LIMIT: ${AGENT_EXECUTE_LIMIT:-1}\e[0m"
            return 1
        fi
    fi
}

# Function to reorganize directory structure
reorganize_directory_structure() {
    echo "Reorganizing directory structure..."

    # First, move the smart_agent directory if it exists in the temp clone
    if [ -d "$TEMP_CLONE_DIR/smart_agent" ]; then
        echo "Found smart_agent directory in blueprint..."

        # Remove existing PROJECT_NAME directory if it exists
        if [ -d "$PROJECT_NAME" ]; then
            rm -rf "$PROJECT_NAME"
        fi

        # Move the smart_agent contents
        mv "$TEMP_CLONE_DIR/smart_agent" "$PROJECT_NAME"
        echo -e "\e[32m✓ Moved smart_agent contents to $PROJECT_NAME/\e[0m"
    else
        echo -e "\e[31m❌ Warning: smart_agent directory not found in blueprint\e[0m"
    fi

    # Now move ALL other files and directories from temp clone to root level
    echo "Moving all other blueprint files and directories to root level..."

    # List what we're about to move (for debugging)
    echo "Files and directories in blueprint:"
    ls -la "$TEMP_CLONE_DIR/"

    # Move everything except smart_agent (which we already moved) and .git
    for item in "$TEMP_CLONE_DIR"/*; do
        if [ -e "$item" ]; then
            item_name=$(basename "$item")

            # Skip smart_agent (already moved) and .git directory
            if [ "$item_name" != "smart_agent" ] && [ "$item_name" != ".git" ]; then
                # If item already exists at root, remove it first
                if [ -e "$item_name" ]; then
                    rm -rf "$item_name"
                    echo -e "\e[33m✓ Removed existing $item_name\e[0m"
                fi

                # Move the item
                mv "$item" ./
                echo -e "\e[32m✓ Moved $item_name to root level\e[0m"
            fi
        fi
    done

    # Also move hidden files (like .gitignore, .env files, etc.) but not .git
    for item in "$TEMP_CLONE_DIR"/.*; do
        if [ -e "$item" ]; then
            item_name=$(basename "$item")

            # Skip . and .. and .git directories
            if [ "$item_name" != "." ] && [ "$item_name" != ".." ] && [ "$item_name" != ".git" ]; then
                # If item already exists at root, remove it first
                if [ -e "$item_name" ]; then
                    rm -rf "$item_name"
                    echo -e "\e[33m✓ Removed existing $item_name\e[0m"
                fi

                # Move the item
                mv "$item" ./
                echo -e "\e[32m✓ Moved hidden file $item_name to root level\e[0m"
            fi
        fi
    done

    # Clean up temp directory
    rm -rf "$TEMP_CLONE_DIR"
    echo -e "\e[32m✓ Cleaned up temporary clone directory\e[0m"

    # Verify the structure is correct
    echo -e "\n\e[32mFinal project structure:\e[0m"
    ls -la ./

    if [ -d "$PROJECT_NAME/src" ]; then
        echo -e "\e[32m✓ Directory structure verified - $PROJECT_NAME/ folder with src/ inside\e[0m"
    else
        echo -e "\e[31m❌ Warning: Expected src/ directory not found in $PROJECT_NAME/\e[0m"
    fi

    # Check for lambda_handler.py at root level
    if [ -f "lambda_handler.py" ]; then
        echo -e "\e[32m✓ Found lambda_handler.py at root level\e[0m"
    else
        echo -e "\e[33m⚠ lambda_handler.py not found at root level (may not be in blueprint)\e[0m"
    fi

    # Check for lambda_handler.py in smart_agent
    if [ -f "$PROJECT_NAME/lambda_handler.py" ]; then
        echo -e "\e[32m✓ Found lambda_handler.py inside $PROJECT_NAME/\e[0m"
    else
        echo -e "\e[33m⚠ lambda_handler.py not found inside $PROJECT_NAME/ (may not be in blueprint)\e[0m"
    fi
}

# Function to clean up agent files based on selected type
cleanup_agent_files() {
    local agent_dir="$PROJECT_NAME/src/agent"
    local config_dir="$PROJECT_NAME/src/config"
    local controllers_dir="$PROJECT_NAME/src/controllers"

    echo "Cleaning up unused agent files for type: $agent_type"

    # Remove unused agent type files
    all_agent_types=("general" "gimlet" "mojito" "daiquiri")

    for type in "${all_agent_types[@]}"; do
        if [ "$type" != "$agent_type" ]; then
            # Remove unused files from agent directory
            if [ -f "$agent_dir/base_agent_${type}.py" ]; then
                rm "$agent_dir/base_agent_${type}.py"
                echo -e "\e[31m- Removed base_agent_${type}.py\e[0m"
            fi

            # Remove unused files from config directory
            if [ -f "$config_dir/agent_${type}.json" ]; then
                rm "$config_dir/agent_${type}.json"
                echo -e "\e[31m- Removed agent_${type}.json\e[0m"
            fi

            # Remove unused files from controllers directory
            if [ -f "$controllers_dir/ExecuteController_${type}.py" ]; then
                rm "$controllers_dir/ExecuteController_${type}.py"
                echo -e "\e[31m- Removed ExecuteController_${type}.py\e[0m"
            fi
        fi
    done

    # Rename selected agent files to standard names (only if not general)
    if [ "$agent_type" != "general" ]; then
        if [ -f "$agent_dir/base_agent_${agent_type}.py" ]; then
            mv "$agent_dir/base_agent_${agent_type}.py" "$agent_dir/base_agent.py"
            echo -e "\e[32m✓ Renamed base_agent_${agent_type}.py to base_agent.py\e[0m"
        fi

        if [ -f "$config_dir/agent_${agent_type}.json" ]; then
            mv "$config_dir/agent_${agent_type}.json" "$config_dir/agent.json"
            echo -e "\e[32m✓ Renamed agent_${agent_type}.json to agent.json\e[0m"
        fi

        if [ -f "$controllers_dir/ExecuteController_${agent_type}.py" ]; then
            mv "$controllers_dir/ExecuteController_${agent_type}.py" "$controllers_dir/ExecuteController.py"
            echo -e "\e[32m✓ Renamed ExecuteController_${agent_type}.py to ExecuteController.py\e[0m"
        fi
    else
        echo -e "\e[32m✓ Using general agent type (default files)\e[0m"
    fi
}

# Function to remove sensitive data from files before git operations
sanitize_files_for_git() {
    echo "Sanitizing files for git commit..."

    # Create a temporary sanitized version of setup.sh for git
    cp setup.sh setup.sh.backup

    # Replace any potential token values with placeholder
    sed -i 's/ghp_[a-zA-Z0-9_]*/GH_TOKEN_PLACEHOLDER/g' setup.sh
    sed -i 's/sk-[a-zA-Z0-9_]*/OPENAI_API_KEY_PLACEHOLDER/g' setup.sh

    echo -e "\e[32m✓ Files sanitized for git commit\e[0m"
}

# Function to restore files after git operations
restore_files_after_git() {
    echo "Restoring original files..."

    if [ -f "setup.sh.backup" ]; then
        mv setup.sh.backup setup.sh
        echo -e "\e[32m✓ Original files restored\e[0m"
    fi
}

# Function to initialize new git repository and push to remote
initialize_new_git_repo() {
    echo "**"
    echo -e "\e[32mInitializing new git repository...\e[0m"
    echo "**"

    # Remove any existing .git directory
    if [ -d ".git" ]; then
        rm -rf ".git"
        echo -e "\e[32m✓ Removed existing .git directory\e[0m"
    fi

    # Initialize new git repository at root level
    git init
    echo -e "\e[32m✓ Initialized new git repository\e[0m"

    # Set git user config if not already set
    if ! git config --get user.email > /dev/null 2>&1; then
        git config user.email "github-actions@github.com"
        git config user.name "GitHub Actions"
        echo -e "\e[32m✓ Set git user configuration\e[0m"
    fi

    # Add remote origin
    git remote add origin "https://$GH_TOKEN:x-oauth-basic@github.com/$GITHUB_ORG/$REPO_NAME.git"
    echo -e "\e[32m✓ Added remote origin\e[0m"

    # Create .gitignore
    cat > .gitignore << EOF
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
env.bak/
venv.bak/
pip-log.txt
pip-delete-this-directory.txt
.pytest_cache/
.coverage
htmlcov/
.tox/
.cache
nosetests.xml
coverage.xml
*.cover
.hypothesis/

# Environment variables
.env
.env.local
.env.*.local

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db

# Logs
logs
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Dependency directories
node_modules/

# Terraform
*.tfstate
*.tfstate.*
.terraform/
.terraform.lock.hcl

# AWS Lambda
deployment.zip
lambda_layer.zip
package/

# Replit
.replit
.upm/
.pythonlibs/
replit.nix
pyproject.toml
poetry.lock

# Local development
.pytest_cache/
.mypy_cache/
dist/
build/
*.egg-info/

# Temporary files
blueprint_temp/

# Backup files
*.backup
EOF

    echo -e "\e[32m✓ Created .gitignore\e[0m"

    # Sanitize files before git operations
    sanitize_files_for_git

    # Stage all files
    git add .
    echo -e "\e[32m✓ Staged all files\e[0m"

    # Create initial commit
    git commit -m "Initial commit: $AGENT_NAME ($agent_type agent type)

- Generated from oneForAll blueprint
- Agent type: $agent_type
- Project structure: single smart_agent/ folder
- External folders: .github, scripts, terraform
- Root level files: lambda_handler.py and others
- S3 deployment configuration with latest-only storage
- Agent-specific DynamoDB table for job state management"
    echo -e "\e[32m✓ Created initial commit\e[0m"

    # Create and switch to main branch
    git branch -M main
    echo -e "\e[32m✓ Set main branch\e[0m"

    # Push to remote repository
    echo -e "\e[32mPushing to remote repository...\e[0m"
    if git push -u origin main; then
        echo -e "\e[32m✓ Successfully pushed to remote repository\e[0m"
        echo -e "\e[32m🔗 Repository: https://github.com/$GITHUB_ORG/$REPO_NAME\e[0m"
    else
        echo -e "\e[31m❌ Failed to push to remote repository\e[0m"
        echo -e "\e[33m⚠ You can push manually later with: git push -u origin main\e[0m"
    fi

    # Restore original files
    restore_files_after_git
}

# Function to create the lambda packaging script
create_lambda_package_script() {
    mkdir -p scripts
    cat > scripts/package-lambda.py << 'EOF'
import os
import shutil
from pathlib import Path

def create_lambda_package():
    """Create Lambda deployment package"""
    print("Creating Lambda deployment package...")
    
    PACKAGE_DIR = Path("package")
    
    # Clean up existing package directory
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    
    PACKAGE_DIR.mkdir()
    
    # Install dependencies
    print("Installing dependencies...")
    os.system(f"pip install -r smart_agent/requirements.txt -t {PACKAGE_DIR}")
    
    # Copy source code
    print("Copying source code...")
    shutil.copytree("smart_agent", PACKAGE_DIR / "smart_agent")
    shutil.copy("lambda_handler.py", PACKAGE_DIR / "lambda_handler.py")
    
    # Copy the Prompt directory if it exists
    if Path("Prompt").exists():
        print("Copying Prompt directory...")
        shutil.copytree("Prompt", PACKAGE_DIR / "Prompt")
    
    # Create deployment zip
    print("Creating deployment package...")
    shutil.make_archive("deployment", "zip", PACKAGE_DIR)
    
    # Get package size
    package_size = os.path.getsize("deployment.zip")
    package_size_mb = package_size / (1024 * 1024)
    
    print(f"Package created: deployment.zip ({package_size_mb:.2f} MB)")
    
    # Clean up package directory
    shutil.rmtree(PACKAGE_DIR)
    
    return package_size_mb

if __name__ == "__main__":
    size = create_lambda_package()
    print(f"Lambda package ready: {size:.2f} MB")
EOF

    echo -e "\e[32m✓ Created Lambda packaging script\e[0m"
}

# Function to create updated terraform main.tf
create_terraform_config() {
    mkdir -p terraform
    cat > terraform/main.tf << 'EOF'
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
EOF

    # Update terraform configuration with actual values
    sed -i "s/AGENT_NAME/$REPO_NAME/g" "terraform/main.tf"
    sed -i "s/ENVIRONMENT/\${var.environment}/g" "terraform/main.tf"
    
    echo -e "\e[32m✓ Created Terraform configuration with agent-specific DynamoDB table\e[0m"
}

# Check if this is a setup run or a regular run
if [ "$1" == "setup" ] || [ ! -d "$PROJECT_NAME" ]; then
    # SETUP MODE
    echo "**"
    echo -e "\e[32mInfo- Starting setup for '$AGENT_NAME' ($agent_type type)\e[0m"
    echo -e "\e[32mGitHub Repository: $REPO_NAME\e[0m"
    echo -e "\e[32mLocal Folder: $PROJECT_NAME\e[0m"
    echo -e "\e[32mS3 Deployment: Latest-only package storage\e[0m"
    echo -e "\e[32mDynamoDB: Agent-specific table for job state\e[0m"
    echo "**"
    echo -e "\n"

    # Create .env file for local development
    echo "Creating .env file for local development..."
    cat > .env << EOF
APP_PORT=${APP_PORT:-8000}
APP_HOST=${APP_HOST:-0.0.0.0}
ALLOW_ORIGINS=${ALLOW_ORIGINS:-http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar}
OPENAI_API_KEY=${OPENAI_API_KEY}
GH_TOKEN=${GH_TOKEN}
AGENT_NAME=${AGENT_NAME}
AGENT_TYPE=${agent_type}
AGENT_EXECUTE_LIMIT=${AGENT_EXECUTE_LIMIT:-1}
EOF

    # Check required environment variables
    echo "Checking environment variables..."
    missing_vars=()

    required_vars=("GH_TOKEN" "OPENAI_API_KEY")

    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            missing_vars+=("$var")
        else
            echo -e "\e[32m✓ Found $var\e[0m"
        fi
    done

    # If missing variables, prompt user to input them
    if [ ${#missing_vars[@]} -gt 0 ]; then
        if ! prompt_missing_variables "${missing_vars[@]}"; then
            echo "**"
            echo -e "\e[31m❌ Setup cannot continue without required environment variables\e[0m"
            echo -e "\e[33m💡 Alternative: Set these variables in your environment:\e[0m"
            for var in "${missing_vars[@]}"; do
                echo -e "\e[33m   export $var=\"your_value_here\"\e[0m"
            done
            echo "**"
            exit 1
        fi
        
        # Update the .env file with the new values
        echo "Updating .env file with provided values..."
        cat > .env << EOF
APP_PORT=${APP_PORT:-8000}
APP_HOST=${APP_HOST:-0.0.0.0}
ALLOW_ORIGINS=${ALLOW_ORIGINS:-http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar}
OPENAI_API_KEY=${OPENAI_API_KEY}
GH_TOKEN=${GH_TOKEN}
AGENT_NAME=${AGENT_NAME}
AGENT_TYPE=${agent_type}
AGENT_EXECUTE_LIMIT=${AGENT_EXECUTE_LIMIT:-1}
EOF
        echo -e "\e[32m✓ Environment file updated with provided values\e[0m"
        
        # Update the BLUEPRINT_REPO_URL with the new GH_TOKEN
        BLUEPRINT_REPO_URL="https://$GH_TOKEN:x-oauth-basic@github.com/Activate-Intelligence/agent-blueprint.git"
    fi

    # Create new GitHub repository
    create_github_repo_with_readme

    # Clone the blueprint repository to a temporary directory
    echo "Downloading blueprint..."

    if [ -d "$TEMP_CLONE_DIR" ]; then
        echo "Removing existing temporary directory..."
        rm -rf "$TEMP_CLONE_DIR"
    fi

    if [ -d "$PROJECT_NAME" ]; then
        echo "Removing existing $PROJECT_NAME folder..."
        rm -rf "$PROJECT_NAME"
    fi

    git clone --branch lambda-merge-poc "$BLUEPRINT_REPO_URL" "$TEMP_CLONE_DIR" || {
        echo -e "\e[31m❌ Failed to clone blueprint repository\e[0m"
        exit 1
    }

    echo -e "\e[32m✓ Blueprint downloaded\e[0m"

    # Reorganize directory structure
    reorganize_directory_structure

    echo "**"
    echo -e "\e[32mConfiguring agent type: $agent_type for '$AGENT_NAME'\e[0m"
    echo "**"

    # Clean up unused agent files
    cleanup_agent_files

    # Create .env.sample for the project
    cat > "$PROJECT_NAME/.env.sample" << EOF
# Environment Configuration Template
# Copy this file to .env and fill in your actual values
# DO NOT commit the .env file - it contains secrets!

APP_PORT=8000
APP_HOST=0.0.0.0
ALLOW_ORIGINS=http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar
OPENAI_API_KEY=sk-proj-YOUR_OPENAI_API_KEY_HERE
AGENT_NAME=$AGENT_NAME
AGENT_TYPE=$agent_type
GH_TOKEN=ghp_YOUR_GITHUB_TOKEN_HERE
AGENT_EXECUTE_LIMIT=1
EOF

    # Clean up requirements.txt
    if [ -f "$PROJECT_NAME/requirements.txt" ]; then
        # Remove duplicates and ensure consistent casing
        sort "$PROJECT_NAME/requirements.txt" | uniq > "$PROJECT_NAME/requirements_tmp.txt"
        mv "$PROJECT_NAME/requirements_tmp.txt" "$PROJECT_NAME/requirements.txt"
        echo -e "\e[32m✓ Cleaned up requirements.txt\e[0m"
    fi

    # Create terraform configuration
    create_terraform_config

    # Create .github/workflows directory
    mkdir -p ".github/workflows"

    # Create GitHub workflow file with S3 deployment
    create_github_workflow

    # Create scripts directory and lambda packaging script
    create_lambda_package_script

    # Create README.md for the local repository
    cat > README.md << EOF
# $AGENT_NAME

This is a custom AI agent built using the oneForAll blueprint framework with optimized S3-based Lambda deployment and agent-specific DynamoDB table.

## Agent Configuration
- **Agent Name**: $AGENT_NAME
- **Agent Type**: $agent_type
- **Repository**: $REPO_NAME
- **Deployment**: S3-based Lambda deployment (latest-only storage)
- **Database**: Agent-specific DynamoDB table for job state management

## Description
$AGENT_NAME is an AI agent designed to help with various tasks using the $agent_type configuration.

## Deployment Architecture
- **S3 Bucket**: 533267084389-lambda-artifacts
- **Storage Strategy**: Latest package only (automatic cleanup)
- **Structure**: $REPO_NAME/dev/ and $REPO_NAME/prod/
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

\`\`\`bash
# Step 1: Clone this repository
git clone https://github.com/$GITHUB_ORG/$REPO_NAME.git
cd $REPO_NAME

# Step 2: Create a .env file with your configuration
cat > .env << 'ENV_EOF'
APP_PORT=8000
APP_HOST=0.0.0.0
ALLOW_ORIGINS=http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar
OPENAI_API_KEY=your_openai_api_key_here
AGENT_NAME=$AGENT_NAME
AGENT_TYPE=$agent_type
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
\`\`\`

## Project Structure

\`\`\`
$REPO_NAME/
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
\`\`\`

## Deployment Information

### S3 Deployment Strategy
- **Latest-Only Storage**: Only the most recent deployment package is stored
- **Automatic Cleanup**: Old packages are automatically deleted before new uploads
- **Consistent Naming**: Uses \`deployment-latest.zip\` for easy identification
- **Metadata Tracking**: Includes deployment timestamp, git SHA, and environment info

### DynamoDB Strategy
- **Agent-Specific Tables**: Each agent gets its own DynamoDB table
- **Table Name**: \`$REPO_NAME-{environment}-jobs\`
- **Billing Mode**: PAY_PER_REQUEST (automatic scaling)
- **Global Secondary Index**: \`status-index\` for efficient status queries
- **Isolation**: Complete data isolation between agents

### S3 Structure
\`\`\`
533267084389-lambda-artifacts/
├── $REPO_NAME/
│   ├── dev/
│   │   └── deployment-latest.zip
│   └── prod/
│       └── deployment-latest.zip
\`\`\`

### DynamoDB Structure
\`\`\`
$REPO_NAME-dev-jobs    # Development environment table
$REPO_NAME-prod-jobs   # Production environment table
\`\`\`

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
- Generated on: $(date)
- S3 Deployment: Latest-only storage optimization
- DynamoDB: Agent-specific table isolation
EOF

    # Create .replit configuration
    cat > .replit << EOL
run = "bash setup.sh run"
language = "python3"
modules = ["python-3.11:v18-20230807-322e88b", "python-3.11:v25-20230920-d4ad2e4"]
hidden = [".pythonlibs", "venv", ".config", "**/pycache", "**/.mypy_cache", "**/*.pyc"]

[env]
VIRTUAL_ENV = "/home/runner/\${REPL_SLUG}/venv"
PATH = "\${VIRTUAL_ENV}/bin:\${PATH}"
PYTHONPATH = "\${REPL_HOME}"
APP_PORT = "${APP_PORT:-8000}"
APP_HOST = "${APP_HOST:-0.0.0.0}"
ALLOW_ORIGINS = "${ALLOW_ORIGINS:-http://localhost:9000,http://localhost:3000,https://api.dev.spritz.cafe,https://api.spritz.cafe,https://app.dev.spritz.cafe,https://app.spritz.cafe,https://api.dev.spritz.activate.bar,https://api.spritz.activate.bar,https://app.dev.spritz.activate.bar,https://spritz.activate.bar}"
OPENAI_API_KEY = "${OPENAI_API_KEY}"
GH_TOKEN = "${GH_TOKEN}"
AGENT_NAME = "${AGENT_NAME}"
AGENT_TYPE = "${agent_type}"
AGENT_EXECUTE_LIMIT = "${AGENT_EXECUTE_LIMIT:-1}"

[debugger]
support = true

[packager]
language = "python3"
ignoredPackages = ["unit_tests"]

[languages]
[languages.python3]
pattern = "**/*.py"
[languages.python3.languageServer]
start = "pylsp"

[deployment]
run = ["sh", "-c", "bash setup.sh run"]
deploymentTarget = "gce"

[[ports]]
localPort = ${APP_PORT:-8000}
externalPort = 80
EOL

    # Setup Python environment
    echo "**"
    echo -e "\e[32mSetting up Python environment...\e[0m"
    echo "**"

    # Disable forced --user installs that cause issues in Replit
    export PIP_USER=0
    unset PYTHONUSERBASE

    # Create virtual environment
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo "✓ Created virtual environment"
    fi

    # Activate virtual environment
    source venv/bin/activate
    echo "✓ Activated virtual environment"

    # Install dependencies
    echo "Installing dependencies..."

    # Upgrade pip first
    pip install --upgrade pip --no-user

    # Install dependencies from requirements.txt
    if [ -f "$PROJECT_NAME/requirements.txt" ]; then
        echo "Installing from $PROJECT_NAME/requirements.txt..."
        pip install --no-user -r "$PROJECT_NAME/requirements.txt"
        echo "✓ Dependencies installed successfully"
    else
        echo "requirements.txt not found. Installing basic dependencies..."
        pip install --no-user fastapi uvicorn openai pydantic python-dotenv
        echo "✓ Basic dependencies installed"
    fi

    # Verify critical packages are installed
    echo "Verifying installation..."
    python -c "import uvicorn, fastapi; print('✓ FastAPI and Uvicorn ready')" || {
        echo "❌ Installation verification failed"
        echo "Attempting to fix..."
        pip install --no-user fastapi uvicorn
    }

    # Set repository secrets AFTER the repository is created and pushed
    set_repo_secrets

    # Initialize new git repository and push to remote
    initialize_new_git_repo

    echo "**"
    echo -e "\e[32m🎉 Setup completed successfully!\e[0m"
    echo -e "\e[32m📁 Agent Name: $AGENT_NAME\e[0m"
    echo -e "\e[32m🔧 Agent Type: $agent_type\e[0m"
    echo -e "\e[32m📂 Local Folder: $PROJECT_NAME/\e[0m"
    echo -e "\e[32m📂 GitHub Repository: https://github.com/$GITHUB_ORG/$REPO_NAME\e[0m"
    echo -e "\e[32m🔗 Repository pushed to: https://github.com/$GITHUB_ORG/$REPO_NAME.git\e[0m"
    echo -e "\e[32m🔐 Repository secrets configured for GitHub Actions\e[0m"
    echo -e "\e[32m☁️  S3 Deployment: Latest-only storage (533267084389-lambda-artifacts)\e[0m"
    echo -e "\e[32m🗄️  DynamoDB: Agent-specific table ($REPO_NAME-{env}-jobs)\e[0m"
    echo -e "\e[32m🧹 Auto-cleanup: Old packages automatically removed\e[0m"
    echo -e "\e[32m🌍 Environment Logic: main→dev, prod*→prod\e[0m"
    echo -e "\e[32m▶️  Ready to run! Click the Run button or use: bash setup.sh run\e[0m"
    echo "**"
    echo -e "\e[32m✓ All files pushed to GitHub automatically\e[0m"
    echo -e "\e[32m✓ Repository secrets configured for CI/CD\e[0m"
    echo -e "\e[32m✓ S3-based Lambda deployment with latest-only storage\e[0m"
    echo -e "\e[32m✓ Agent-specific DynamoDB table with PAY_PER_REQUEST billing\e[0m"
    echo -e "\e[32m✓ Environment-specific resources to prevent conflicts\e[0m"
    echo "**"

else
    # RUN MODE
    echo "**"
    echo -e "\e[32mPreparing to run the agent...\e[0m"
    echo "**"

    # Load environment variables first
    if [ -f ".env" ]; then
        export $(grep -v '^#' .env | xargs)
        echo "Loaded environment variables from .env"
    fi

    # Disable forced --user installs for Replit compatibility
    export PIP_USER=0
    unset PYTHONUSERBASE

    # Ensure virtual environment exists and is activated
    if [ ! -d "venv" ]; then
        echo "Virtual environment not found. Creating..."
        python3 -m venv venv
    fi

    # Activate virtual environment
    source venv/bin/activate
    echo "✓ Activated virtual environment"

    # Check if dependencies are installed, install if missing
    if ! python -c "import uvicorn" 2>/dev/null; then
        echo "Dependencies missing. Installing..."
        pip install --upgrade pip --no-user

        if [ -f "$PROJECT_NAME/requirements.txt" ]; then
            pip install --no-user -r "$PROJECT_NAME/requirements.txt"
            echo "✓ Installed dependencies from $PROJECT_NAME/requirements.txt"
        else
            echo "requirements.txt not found. Installing basic dependencies..."
            pip install --no-user fastapi uvicorn openai pydantic python-dotenv
        fi
    else
        echo "✓ Dependencies are already installed"
    fi

    # Verify installation
    echo "Verifying installation..."
    python -c "import uvicorn, fastapi; print('✓ FastAPI and Uvicorn are ready')" || {
        echo "❌ Installation verification failed"
        echo "Attempting emergency install..."
        pip install --no-user --force-reinstall fastapi uvicorn
        exit 1
    }

    echo "**"
    echo -e "\e[32mStarting ${AGENT_NAME:-Agent} (${AGENT_TYPE:-general} type)...\e[0m"
    echo -e "\e[32mS3 Deployment: Latest-only storage enabled\e[0m"
    echo -e "\e[32mDynamoDB: Agent-specific table enabled\e[0m"
    echo "**"

    # Set Python path and run the application
    export PYTHONPATH="${REPL_HOME}:${PYTHONPATH}"
    cd "$PROJECT_NAME"

    echo "Starting server on http://0.0.0.0:${APP_PORT:-8000}"
    echo "API documentation will be available at: http://0.0.0.0:${APP_PORT:-8000}/docs"
    echo ""

    python3 main.py

fi