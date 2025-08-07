# from ..utils.temp_db import temp_data
from ..config.logger import Logger
from ..utils.webhook import call_webhook_with_error, call_webhook_with_success
from openai import OpenAI
import openai
from .prompt_extract import extract_prompts
import os
from datetime import datetime
from .get_prompt_from_git import main as promptDownloader
import json
from .agent_config import fetch_agent_config
from .rss_feed_processor import create_feed_processor
import time

# Configuration flag - Change this to switch between dev and prod modes
ENVIRONMENT_MODE = "dev"  # Change to "prod" for production or dev for development

# Neo4j credentials
NEO4J_URL = "neo4j+s://ff9f9095.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "BTpQLS4NHJ3aBpYS-7ec4hl1P9cE93L8QQa7H-enE0k"

def get_openai_client():
    """Get OpenAI client with lazy initialization"""
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return OpenAI(api_key=openai_api_key)

def get_environment_mode():
    """Get the current environment mode (dev or prod)"""
    return ENVIRONMENT_MODE.lower()

def get_prompt_file_path():
    """Get the appropriate prompt file path based on environment mode"""
    mode = get_environment_mode()
    
    if mode == "dev":
        # In dev mode, try /tmp/Prompt first, fallback to Prompt
        tmp_prompt_path = '/tmp/Prompt/source_filtering_prompt.yaml'
        if os.path.exists(tmp_prompt_path):
            return tmp_prompt_path
        else:
            return 'Prompt/source_filtering_prompt.yaml'
    else:
        # In prod mode, only use Prompt folder
        return 'Prompt/source_filtering_prompt.yaml'

def llm(context, inquiry):
    prompt_file_path = get_prompt_file_path()
    replacements = {"articles": context}
    system_prompt, user_prompt, model_params = extract_prompts(prompt_file_path,
                                                 **replacements)
    print("---"*30)
    print(f"system_prompt: {system_prompt}, user_prompt: {user_prompt}, model_params: {model_params}")
    print("---"*30)
    
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=model_params['name'],
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt  
                },
            ],
            text={"format": {"type": "json_object"}},
            reasoning={"effort": "medium"})

        # Extracting and cleaning the GPT response
        result = response.choices[0].message.content.strip()
        return result
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return None

def base_agent(payload):
    try:
        print(payload)
        
        # Check environment mode
        mode = get_environment_mode()
        print(f"Running in {mode} mode")
        
        # Download the latest prompt files only in dev mode
        if mode == "dev":
            print("Dev mode: Downloading latest prompt files")
            promptDownloader()
        else:
            print("Prod mode: Skipping prompt download")
       
        # Get agent configuration
        agent_config_doc = fetch_agent_config()
        print(f"the agent config: {agent_config_doc}")
        agent_name = agent_config_doc.get('name', 'UnknownAgent')

        # Generate request ID
        request_id = payload.get(
            'request_id', f"req-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        print(f"Request ID: {request_id}")
        
        call_webhook_with_success(
            payload.get('id'), {
                "status": "inprogress",
                "data": {
                    "info": "Starting fully multithreaded RSS feed and article processing",
                },
            })
        
        # Create RSS Feed Processor with configurable thread counts
        max_feed_workers = 5  # Default 5 feed workers
        max_article_workers = 3  # Default 3 article workers per feed
        
        print(f"Starting RSS feed scraping with {max_feed_workers} feed workers and {max_article_workers} article workers per feed...")
        print(f"Total potential concurrent article processing: {max_feed_workers * max_article_workers} threads")
        
        feed_processor = create_feed_processor(
            NEO4J_URL, 
            NEO4J_USER, 
            NEO4J_PASSWORD, 
            max_feed_workers=max_feed_workers,
            max_article_workers=max_article_workers
        )
        result = feed_processor.process_all_feeds(days_back=1)
        
        if result["success"]:
            call_webhook_with_success(
                payload.get('id'), {
                    "status": "inprogress",
                    "data": {
                        "info": f"Successfully processed {result['total_articles']} articles from {result['processed_sources']} RSS feeds using multithreaded processing"
                    },
                })
        else:
            call_webhook_with_error(payload.get('id'), result["message"], 500)
            return
        
        # Reduced wait time since multithreading already speeds up the process significantly
        time.sleep(15)  # Further reduced from 30 seconds due to much faster processing
        
        name = payload.get('name', '')
        performance_stats = result.get('performance_stats', {})
        msg = f"Hi {name}, successfully processed {result['total_articles']} articles from {result['processed_sources']} RSS feeds using fully multithreaded processing! Found {result.get('total_articles_found', 0)} total articles, processed {result.get('total_articles_processed', 0)} individual articles with {performance_stats.get('feed_workers', 0)} feed workers and {performance_stats.get('article_workers_per_feed', 0)} article workers per feed ({result.get('successful_sources', 0)} successful, {result.get('failed_sources', 0)} failed sources)."
        print(msg)

        call_webhook_with_success(payload.get('id'), {
            "status": "completed",
            "data": {
                "title": f"Fully multithreaded RSS processing completed",
                "info": f"Processed {result['total_articles']} articles from {result['processed_sources']} sources"
            },
        })

        resp = {"name": "output", "type": "longText", "data": msg}
        return resp

    except Exception as e:
        print(f"Error in base_agent: {e}")
        call_webhook_with_error(payload.get('id'), str(e), 500)