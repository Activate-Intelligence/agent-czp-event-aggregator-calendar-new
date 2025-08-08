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
import time
# Heavy processing modules - only import when running in ECS
try:
    from .camera_events import camera_main
    from .senato_events import senato_main
    HEAVY_MODULES_AVAILABLE = True
except ImportError:
    print("Heavy processing modules not available (Lambda mode)")
    HEAVY_MODULES_AVAILABLE = False
    camera_main = None
    senato_main = None

import requests
from io import BytesIO
import re
import json
from dateutil import tz
from dotenv import load_dotenv
import concurrent.futures

# Heavy imports - only import when available  
try:
    from bs4 import BeautifulSoup
    HEAVY_IMPORTS_AVAILABLE = True
except ImportError:
    print("Heavy imports not available (Lambda mode)")
    BeautifulSoup = None
    HEAVY_IMPORTS_AVAILABLE = False

# Configuration flag - Change this to switch between dev and prod modes
ENVIRONMENT_MODE = "dev"  # Change to "prod" for production or dev for development

def get_openai_client():
    """Get OpenAI client, initializing it lazily when first needed."""
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    return OpenAI(api_key=openai_api_key)


load_dotenv()  # This will load environment variables from the .env file


# OpenAI client is initialized lazily via get_openai_client() function above

logger = Logger()

def check_senato():
    # Check if BeautifulSoup is available (ECS mode)
    if not HEAVY_IMPORTS_AVAILABLE or BeautifulSoup is None:
        print("BeautifulSoup not available - skipping senato check")
        return True, "unknown-week-lambda"
        
    # Get current week from website
    response = requests.get(
        "https://www.senato.it/CLS/pub/quadro/permanenti-giunte")
    soup = BeautifulSoup(response.content, 'html.parser')
    current_week = soup.find('div',
                             class_='sxWideComm').find('h2').text.strip()

    # Get stored week from file
    stored_week = None
    if os.path.exists("current_week.txt"):
        with open("current_week.txt", 'r') as f:
            stored_week = f.read().strip()

    print(f"Current week: {current_week}")
    print(f"Stored week: {stored_week}")

    # Check if same
    if current_week == stored_week:
        print("Already processed this week")
        return False, current_week
    else:
        print("New week! Processing...")
        # Save current week

    return True, current_week


def check_camera():
    try:
        # Check if BeautifulSoup is available (ECS mode)
        if not HEAVY_IMPORTS_AVAILABLE or BeautifulSoup is None:
            print("BeautifulSoup not available - skipping camera check")
            return True, "unknown-week-camera-lambda"
            
        # Go to the weekly tab using the correct URL
        weekly_url = "https://www.camera.it/leg19/76?active_tab_3806=3811"
        print(f"Accessing weekly tab: {weekly_url}")

        response = requests.get(weekly_url)
        soup = BeautifulSoup(response.content, 'html.parser')

        # Look for the week text
        week_text = soup.find(string=lambda text: text and 'Settimana dal' in
                              text and '2025' in text)

        if week_text:
            current_week_camera = week_text.strip()
            print(f"Found camera week: {current_week_camera}")
        else:
            print("Could not find week information in weekly tab")

        # Get stored week from file
        stored_week_camera = None
        if os.path.exists("current_week_camera.txt"):
            with open("current_week_camera.txt", 'r') as f:
                stored_week_camera = f.read().strip()

        print(f"Current camera week: {current_week_camera}")
        print(f"Stored camera week: {stored_week_camera}")

        if current_week_camera == stored_week_camera:
            print("Already processed this camera week")
            return False, current_week_camera
        else:
            print("New camera week! Processing...")
            # with open("current_week_camera.txt", 'w') as f:
            #     f.write(current_week_camera)
            return True, current_week_camera

    except Exception as e:
        print(f"Error: {e}")
        return True


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
        
        
        # CHECK SENATO HAS NEW UPDATED CALENDAR.
        out_s, current_week = check_senato()
        print(f"Check Senato {out_s, current_week}")

        call_webhook_with_success(payload.get('id'), {
            "status": "inprogress",
            "data": {
                "title": f"Checking if Senato Calendar is updated.",
                "info": "Processing",
            },
        })

        # CHECK CAMERA HAS NEW UPDATED CALENDAR.
        out_c, current_week_camera = check_camera()
        print(f"Check Senato {out_c, current_week_camera}")

        call_webhook_with_success(payload.get('id'), {
            "status": "inprogress",
            "data": {
                "title": f"checking if Camera Calendar is updated.",
                "info": "Processing",
            },
        })

        print(f"DEBUG: out_s = {out_s}, out_c = {out_c}")
        # Option 3: If either is False
        if out_s == False or out_c == False:
            return {
                "name": "output",
                "type": "shortText",
                "data": "Already processed this week"
            }

        with open("current_week.txt", 'w') as f:
            f.write(current_week)
        print("Week saved to current_week.txt")

        with open("current_week_camera.txt", 'w') as f:
            f.write(current_week_camera)
        print("Camera week saved to current_week_camera.txt")

        # Only run heavy processing if modules are available (ECS mode)
        if not HEAVY_MODULES_AVAILABLE:
            msg = "Calendar processing modules not available in Lambda mode. Use ECS for full processing."
            resp = {"name": "output", "type": "shortText", "data": msg}
            return resp
       
        # Call the heavy processing functions only if they're available
        if senato_main:
            senato_main()
            call_webhook_with_success(payload.get('id'), {
                "status": "inprogress",
                "data": {
                    "title": f"senato_main() is done",
                    "info": "Processing",
                },
            })
        
        if camera_main:
            camera_main()
            call_webhook_with_success(payload.get('id'), {
                "status": "inprogress",
                "data": {
                    "title": f"camera_main() is done",
                    "info": "Processing",
                },
            })
        
        
        

        msg = "Calendar Agent Task Completed Successfully"
        resp = {"name": "output", "type": "shortText", "data": msg}
        return resp

    except Exception as e:
        print(f"Error in base_agent: {e}")
        # raise call_webhook_with_error(str(e), 500) # OLD VERSION SINGLE THREADED
        call_webhook_with_error(payload.get('id'), str(e), 500) # MULTI THREADED
