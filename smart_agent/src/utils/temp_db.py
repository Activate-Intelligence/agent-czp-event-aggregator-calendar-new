import os
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
import json
from typing import Dict, List, Optional, Any

# Get table name from environment variable set by Terraform
TABLE_NAME = os.environ.get("JOB_TABLE")

if not TABLE_NAME:
    # Fallback: construct table name from environment variables
    function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown-agent")
    environment = os.environ.get("ENVIRONMENT", "dev")
    
    # Extract agent name from function name (remove environment suffix)
    agent_name = function_name.replace(f"-{environment}", "") if function_name.endswith(f"-{environment}") else function_name
    TABLE_NAME = f"{agent_name}-jobs"
    
    print(f"Warning: JOB_TABLE not set, using constructed name: {TABLE_NAME}")

print(f"Using DynamoDB table: {TABLE_NAME}")

# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

def get_table_info() -> Dict[str, Any]:
    """Get information about the DynamoDB table"""
    try:
        response = table.meta.client.describe_table(TableName=TABLE_NAME)
        table_info = response['Table']
        return {
            "table_name": table_info['TableName'],
            "table_status": table_info['TableStatus'],
            "item_count": table_info.get('ItemCount', 0),
            "table_size_bytes": table_info.get('TableSizeBytes', 0),
            "billing_mode": table_info.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED'),
            "creation_date": table_info.get('CreationDateTime', '').isoformat() if table_info.get('CreationDateTime') else None,
            "global_secondary_indexes": [
                {
                    "index_name": gsi['IndexName'],
                    "hash_key": gsi['KeySchema'][0]['AttributeName'],
                    "projection_type": gsi['Projection']['ProjectionType']
                } for gsi in table_info.get('GlobalSecondaryIndexes', [])
            ]
        }
    except ClientError as e:
        print(f"get_table_info error: {e}")
        return {"error": str(e)}

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific job by ID"""
    print("GET JOB IS CALLED")
    print(f"get_job called with job_id: {job_id}")
    if not job_id:
        print("get_job error: job_id is empty")
        return None
    try:
        response = table.get_item(Key={"id": job_id})
        print(f"get_job response: {response}")
        return response.get("Item")
    except ClientError as e:
        print(f"get_job error: {e}")
        return None

def add_job(job: Dict[str, Any]) -> bool:
    """Add a new job to the table"""
    try:
        table.put_item(Item=job)
        print(f"Added job: {job.get('id', 'unknown')} to table {TABLE_NAME}")
        return True
    except ClientError as e:
        print(f"add_job error: {e}")
        return False

def remove_job(job_id: str) -> bool:
    """Remove a job from the table"""
    try:
        table.delete_item(Key={"id": job_id})
        print(f"Removed job: {job_id} from table {TABLE_NAME}")
        return True
    except ClientError as e:
        print(f"remove_job error: {e}")
        return False

def list_active_jobs(status_filter: str = "inprogress") -> List[Dict[str, Any]]:
    """List jobs with specific status using GSI for efficient querying"""
    try:
        # Use GSI for efficient status queries
        response = table.query(
            IndexName="status-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("status").eq(status_filter)
        )
        jobs = response.get("Items", [])
        print(f"Found {len(jobs)} jobs with status '{status_filter}' in table {TABLE_NAME}")
        return jobs
    except ClientError as e:
        print(f"list_active_jobs error (GSI query): {e}")
        # Fallback to scan if GSI query fails
        try:
            response = table.scan(
                FilterExpression=Attr("status").eq(status_filter)
            )
            jobs = response.get("Items", [])
            print(f"Fallback scan found {len(jobs)} jobs with status '{status_filter}' in table {TABLE_NAME}")
            return jobs
        except ClientError as scan_error:
            print(f"list_active_jobs scan fallback error: {scan_error}")
            return []

def list_all_jobs() -> List[Dict[str, Any]]:
    """List all jobs in the table"""
    try:
        response = table.scan()
        jobs = response.get("Items", [])
        
        # Handle pagination if there are more items
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            jobs.extend(response.get("Items", []))
        
        print(f"Found {len(jobs)} total jobs in table {TABLE_NAME}")
        return jobs
    except ClientError as e:
        print(f"list_all_jobs error: {e}")
        return []

def update_job_fields(job_id: str, updates: Dict[str, Any]) -> bool:
    """
    Updates specific fields in a job using DynamoDB UpdateItem.
    
    Args:
        job_id: The job ID to update
        updates: Dictionary of field names and values to update
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Build update expression
        update_expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates.keys())
        expression_attrs = {f"#{k}": k for k in updates.keys()}
        value_attrs = {f":{k}": v for k, v in updates.items()}
        
        table.update_item(
            Key={"id": job_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expression_attrs,
            ExpressionAttributeValues=value_attrs
        )
        print(f"Updated job {job_id} with fields: {list(updates.keys())} in table {TABLE_NAME}")
        return True
    except ClientError as e:
        print(f"update_job_fields error: {e}")
        return False

def get_jobs_by_status(status: str) -> List[Dict[str, Any]]:
    """Get all jobs with a specific status (alias for list_active_jobs)"""
    return list_active_jobs(status)

def get_job_count_by_status() -> Dict[str, int]:
    """Get count of jobs grouped by status"""
    try:
        all_jobs = list_all_jobs()
        status_counts = {}
        
        for job in all_jobs:
            status = job.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print(f"Job counts by status in table {TABLE_NAME}: {status_counts}")
        return status_counts
    except Exception as e:
        print(f"get_job_count_by_status error: {e}")
        return {}

def cleanup_completed_jobs(max_age_hours: int = 24) -> int:
    """
    Remove completed jobs older than specified hours
    
    Args:
        max_age_hours: Maximum age in hours for completed jobs
        
    Returns:
        int: Number of jobs cleaned up
    """
    try:
        import datetime
        
        cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=max_age_hours)
        cutoff_timestamp = cutoff_time.timestamp()
        
        completed_jobs = get_jobs_by_status("completed")
        cleaned_count = 0
        
        for job in completed_jobs:
            # Assuming jobs have a 'completed_at' or 'updated_at' timestamp
            job_timestamp = job.get('completed_at') or job.get('updated_at')
            
            if job_timestamp and float(job_timestamp) < cutoff_timestamp:
                if remove_job(job['id']):
                    cleaned_count += 1
        
        print(f"Cleaned up {cleaned_count} completed jobs older than {max_age_hours} hours from table {TABLE_NAME}")
        return cleaned_count
    except Exception as e:
        print(f"cleanup_completed_jobs error: {e}")
        return 0


def cleanup_stale_jobs(max_age_seconds: int = 900) -> int:
    """Remove jobs that are no longer active or are older than the given age."""
    try:
        import time

        now = time.time()
        all_jobs = list_all_jobs()
        cleaned = 0

        for job in all_jobs:
            job_id = job.get("id")
            status = job.get("status")
            timestamp = float(job.get("timestamp", 0))

            if status != "inprogress" or (timestamp and now - timestamp > max_age_seconds):
                if job_id and remove_job(job_id):
                    cleaned += 1

        if cleaned:
            print(f"Cleaned up {cleaned} stale jobs from table {TABLE_NAME}")

        return cleaned
    except Exception as e:
        print(f"cleanup_stale_jobs error: {e}")
        return 0

def health_check() -> Dict[str, Any]:
    """Perform a health check on the DynamoDB table"""
    try:
        # Try to get table info
        table_info = get_table_info()
        
        if "error" in table_info:
            return {
                "status": "unhealthy",
                "table_name": TABLE_NAME,
                "error": table_info["error"]
            }
        
        # Try a simple query
        test_response = table.scan(Limit=1)
        
        return {
            "status": "healthy",
            "table_name": TABLE_NAME,
            "table_status": table_info.get("table_status"),
            "item_count": table_info.get("item_count"),
            "billing_mode": table_info.get("billing_mode"),
            "can_query": True
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "table_name": TABLE_NAME,
            "error": str(e)
        }

# Initialize and verify table on import
def _initialize_table():
    """Initialize and verify the table exists"""
    try:
        table_info = get_table_info()
        if "error" not in table_info:
            print(f"Successfully connected to DynamoDB table: {TABLE_NAME}")
            print(f"Table status: {table_info.get('table_status')}")
            print(f"Billing mode: {table_info.get('billing_mode')}")
            print(f"Item count: {table_info.get('item_count')}")
            
            # Check if GSI exists
            gsi_info = table_info.get('global_secondary_indexes', [])
            if gsi_info:
                print(f"Global Secondary Indexes: {[gsi['index_name'] for gsi in gsi_info]}")
        else:
            print(f"Warning: Could not connect to table {TABLE_NAME}: {table_info.get('error')}")
    except Exception as e:
        print(f"Warning: Table initialization check failed: {e}")

# Run initialization check
_initialize_table()
