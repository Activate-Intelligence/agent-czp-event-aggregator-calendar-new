# from ..utils.temp_db import temp_data
from ..config.logger import Logger
from ..utils.webhook import call_webhook_with_error, call_webhook_with_success
from openai import OpenAI
import openai
from .prompt_extract import extract_prompts
import os
from datetime import datetime, timedelta
from .get_prompt_from_git import main as promptDownloader
import json
from .agent_config import fetch_agent_config
import time
# ECS-only environment - import processing modules directly
from .camera_events import camera_main
from .senato_events import senato_main

import requests
from io import BytesIO
import re
import json
from dateutil import tz
from dotenv import load_dotenv
import concurrent.futures

# ECS environment - import BeautifulSoup directly
from bs4 import BeautifulSoup

# Import Neo4j for database checking
from neo4j import GraphDatabase

# Configuration flag - Change this to switch between dev and prod modes
ENVIRONMENT_MODE = "dev"  # Change to "prod" for production or dev for development

def get_openai_client():
    """Get OpenAI client, initializing it lazily when first needed."""
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    return OpenAI(api_key=openai_api_key)


load_dotenv()  # This will load environment variables from the .env file

# OpenAI client is initialized lazily via get_openai_client() function above

logger = Logger()

class Neo4jWeekChecker:
    """Helper class to check if a week has been processed in Neo4j"""
    
    def __init__(self):
        # Neo4j Configuration (same as in senato_events.py)
        self.uri = "neo4j+s://c94a0c28.databases.neo4j.io"
        self.username = "neo4j"
        self.password = "W0pumaSXNH7U2ZfsNPl4gB1tS4Iw1e-79LbKD7e05fk"
        self.driver = None
    
    def connect(self):
        """Establish connection to Neo4j"""
        if not self.driver:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
    
    def close(self):
        """Close Neo4j connection"""
        if self.driver:
            self.driver.close()
            self.driver = None
    
    def get_next_monday_friday(self):
        """Get the next Monday-Friday range (the week we want events for)"""
        today = datetime.now().date()
        
        # Find next Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0 and today.weekday() != 0:  # If today is not Monday
            days_until_monday = 7
        elif today.weekday() == 0:  # If today is Monday
            days_until_monday = 0
        
        monday = today + timedelta(days=days_until_monday)
        friday = monday + timedelta(days=4)
        
        return monday, friday
    
    def check_events_exist_for_week(self, source_type=None):
        """
        Check if events exist for the target week in Neo4j
        
        Args:
            source_type: Optional filter by source type ('Senato' or 'Camera')
        
        Returns:
            tuple: (has_events: bool, event_count: int, week_string: str)
        """
        self.connect()
        
        try:
            monday, friday = self.get_next_monday_friday()
            monday_str = monday.strftime("%Y-%m-%d")
            friday_str = friday.strftime("%Y-%m-%d")
            week_string = f"Settimana dal {monday.strftime('%-d %B')} al {friday.strftime('%-d %B %Y')}"
            
            with self.driver.session() as session:
                # Build the query based on source type
                if source_type:
                    query = """
                    MATCH (source:Calendar_Source)-[:HAS_EVENT]->(event:Event)
                    WHERE event.date >= $monday_str 
                    AND event.date <= $friday_str
                    AND source.type = $source_type
                    RETURN count(event) as event_count
                    """
                    result = session.run(query, 
                                       monday_str=monday_str, 
                                       friday_str=friday_str,
                                       source_type=source_type)
                else:
                    query = """
                    MATCH (event:Event)
                    WHERE event.date >= $monday_str 
                    AND event.date <= $friday_str
                    RETURN count(event) as event_count
                    """
                    result = session.run(query, 
                                       monday_str=monday_str, 
                                       friday_str=friday_str)
                
                record = result.single()
                event_count = record["event_count"] if record else 0
                
                print(f"Found {event_count} {source_type or 'total'} events for week {monday_str} to {friday_str}")
                
                return event_count > 0, event_count, week_string
                
        except Exception as e:
            print(f"Error checking Neo4j for week events: {e}")
            # If there's an error, return False to allow processing
            return False, 0, ""
        finally:
            self.close()
    
    def clear_week_events(self, source_type=None):
        """
        Optional: Clear events for a specific week if needed for re-processing
        
        Args:
            source_type: Optional filter by source type ('Senato' or 'Camera')
        """
        self.connect()
        
        try:
            monday, friday = self.get_next_monday_friday()
            monday_str = monday.strftime("%Y-%m-%d")
            friday_str = friday.strftime("%Y-%m-%d")
            
            with self.driver.session() as session:
                if source_type:
                    query = """
                    MATCH (source:Calendar_Source)-[:HAS_EVENT]->(event:Event)
                    WHERE event.date >= $monday_str 
                    AND event.date <= $friday_str
                    AND source.type = $source_type
                    DETACH DELETE event
                    """
                    session.run(query, 
                              monday_str=monday_str, 
                              friday_str=friday_str,
                              source_type=source_type)
                else:
                    query = """
                    MATCH (event:Event)
                    WHERE event.date >= $monday_str 
                    AND event.date <= $friday_str
                    DETACH DELETE event
                    """
                    session.run(query, 
                              monday_str=monday_str, 
                              friday_str=friday_str)
                
                print(f"Cleared {source_type or 'all'} events for week {monday_str} to {friday_str}")
                
        except Exception as e:
            print(f"Error clearing events: {e}")
        finally:
            self.close()


def check_senato_neo4j():
    """Check if Senato events for the target week exist in Neo4j"""
    checker = Neo4jWeekChecker()
    has_events, event_count, week_string = checker.check_events_exist_for_week(source_type='Senato')
    
    if has_events:
        print(f"Already processed Senato for week: {week_string} ({event_count} events found)")
        return False, week_string
    else:
        print(f"No Senato events found for week: {week_string}. Processing needed.")
        return True, week_string


def check_camera_neo4j():
    """Check if Camera events for the target week exist in Neo4j"""
    checker = Neo4jWeekChecker()
    has_events, event_count, week_string = checker.check_events_exist_for_week(source_type='Camera')
    
    if has_events:
        print(f"Already processed Camera for week: {week_string} ({event_count} events found)")
        return False, week_string
    else:
        print(f"No Camera events found for week: {week_string}. Processing needed.")
        return True, week_string


def check_senato():
    """Legacy function - now uses Neo4j instead of web scraping"""
    return check_senato_neo4j()


def check_camera():
    """Legacy function - now uses Neo4j instead of web scraping"""
    return check_camera_neo4j()


def send_post_request(org, agent):
    # Define the URL for the external API endpoint
    url = "https://api.spritz.activate.bar/v2/Job"

    # Define the payload with the received HTML content
    payload = {"inputs": [], "agentId": agent, "organizationId": org}

    # Define the headers, including the API token without 'Bearer' and the Origin header
    headers = {
        'Content-Type': 'application/json',
        'Authorization':
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbnw2NWE2NmQzNWE2ZTFiMmM3MGRkM2FjZTUiLCJpYXQiOjE3NDA2NTM1NDQsImV4cCI6MTg5ODMzMzU0NH0.-DEiDvkqkxuRKveyrRUcXRg6g4RTfRA3Ul_EnFh--Y8',
        'Origin': 'https://api.spritz.activate.bar'
    }

    # Make the POST request to the external API endpoint
    requests.post(url, data=json.dumps(payload), headers=headers)


def get_environment_mode():
    """Get the current environment mode (dev or prod)"""
    return ENVIRONMENT_MODE.lower()

def get_prompt_file_path():
    """Get the appropriate prompt file path based on environment mode"""
    mode = get_environment_mode()
    
    if mode == "dev":
        # In dev mode, try /tmp/Prompt first, fallback to Prompt
        tmp_prompt_path = '/tmp/Prompt/GimletGPT.yaml'
        if os.path.exists(tmp_prompt_path):
            return tmp_prompt_path
        else:
            return 'Prompt/GimletGPT.yaml'
    else:
        # In prod mode, only use Prompt folder
        return 'Prompt/GimletGPT.yaml'

def llm(context, inquiry):
    prompt_file_path = get_prompt_file_path()
    replacements = {"context": context, "inquiry": inquiry}
    system_prompt, user_prompt, model_params = extract_prompts(prompt_file_path,
                                                 **replacements)
    print("---"*30)
    print(f"system_prompt: {system_prompt}, user_prompt: {user_prompt}, model_params: {model_params}")
    print("---"*30)
    
    try:
        response = get_openai_client().chat.completions.create(
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
            temperature=model_params['temperature'])

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
            # promptDownloader()
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
        
        # CHECK SENATO HAS EVENTS FOR TARGET WEEK IN NEO4J
        out_s, current_week = check_senato_neo4j()
        print(f"Check Senato in Neo4j: {out_s}, {current_week}")

        call_webhook_with_success(payload.get('id'), {
            "status": "inprogress",
            "data": {
                "title": f"Checking if Senato events exist in database for target week.",
                "info": "Processing",
            },
        })

        # CHECK CAMERA HAS EVENTS FOR TARGET WEEK IN NEO4J
        out_c, current_week_camera = check_camera_neo4j()
        print(f"Check Camera in Neo4j: {out_c}, {current_week_camera}")

        call_webhook_with_success(payload.get('id'), {
            "status": "inprogress",
            "data": {
                "title": f"Checking if Camera events exist in database for target week.",
                "info": "Processing",
            },
        })

        print(f"DEBUG: out_s = {out_s}, out_c = {out_c}")
        
        # If both sources already have events for the target week
        if out_s == False and out_c == False:
            return {
                "name": "output",
                "type": "shortText",
                "data": f"Already processed both Senato and Camera for week: {current_week}"
            }
        
        # Process whichever source needs processing
        if out_s == True:
            print(f"Processing Senato for week: {current_week}")
            senato_main()
            call_webhook_with_success(payload.get('id'), {
                "status": "inprogress",
                "data": {
                    "title": f"senato_main() completed",
                    "info": "Processing",
                },
            })
        else:
            print(f"Skipping Senato - already has {current_week} in database")
        
        if out_c == True:
            print(f"Processing Camera for week: {current_week_camera}")
            camera_main()
            call_webhook_with_success(payload.get('id'), {
                "status": "inprogress",
                "data": {
                    "title": f"camera_main() completed",
                    "info": "Processing",
                },
            })
        else:
            print(f"Skipping Camera - already has {current_week_camera} in database")
        
        # Prepare response message
        processed_items = []
        if out_s == True:
            processed_items.append("Senato")
        if out_c == True:
            processed_items.append("Camera")
        
        if processed_items:
            msg = f"Calendar Agent Task Completed - Processed: {', '.join(processed_items)} for week {current_week}"
        else:
            msg = f"Calendar Agent Task Completed - No processing needed, week {current_week} already in database"
        
        resp = {"name": "output", "type": "shortText", "data": msg}
        return resp

    except Exception as e:
        print(f"Error in base_agent: {e}")
        # raise call_webhook_with_error(str(e), 500) # OLD VERSION SINGLE THREADED
        call_webhook_with_error(payload.get('id'), str(e), 500) # MULTI THREADED


# # Optional: Add a utility function to force re-processing if needed
# def force_reprocess_week(source_type=None):
#     """
#     Utility function to clear a week's events and force re-processing
    
#     Args:
#         source_type: 'Senato', 'Camera', or None for both
#     """
#     checker = Neo4jWeekChecker()
#     checker.clear_week_events(source_type)
#     print(f"Cleared {source_type or 'all'} events for target week. Next run will reprocess.")