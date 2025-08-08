# step1_scrape.py
import requests
from bs4 import BeautifulSoup
import re
from ..utils.webhook import call_webhook_with_error, call_webhook_with_success

import time
import json
import os
from .prompt_extract import extract_prompts
from .get_prompt_from_git import main as promptDownloader
import openai

import pandas as pd
import traceback

from neo4j import GraphDatabase
from datetime import datetime, timedelta


def get_openai_api_key():
    """Get OpenAI API key from environment variables."""
    return os.environ.get("OPENAI_API_KEY")


from neo4j import GraphDatabase

def get_next_monday_friday():
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

    print(f"Target week: {monday} to {friday}")
    return monday, friday

def is_date_in_current_week(date_str):
    """Check if a given date string (YYYY-MM-DD format) falls within the target week."""
    if not date_str:
        return False

    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_date, end_date = get_next_monday_friday()
        return start_date <= event_date <= end_date
    except (ValueError, TypeError):
        print(f"Warning: Could not parse date '{date_str}', skipping event")
        return False

def filter_events_by_current_week(events):
    """Filter a list of events to only include those in the current week."""
    if not events:
        return []

    start_date, end_date = get_next_monday_friday()
    print(f"Filtering events for week: {start_date} to {end_date}")

    filtered_events = []
    skipped_count = 0

    for event in events:
        event_date = event.get('Date', '')

        if is_date_in_current_week(event_date):
            filtered_events.append(event)
        else:
            skipped_count += 1

    print(f"Filtered {len(filtered_events)} events (skipped {skipped_count} outside current week)")
    return filtered_events

def filter_commission_events_by_current_week(all_events):
    """Filter commission events dictionary by target week."""
    if not all_events:
        return {}

    start_date, end_date = get_next_monday_friday()
    print(f"Filtering commission events for week: {start_date} to {end_date}")

    filtered_all_events = {}
    total_original = 0
    total_filtered = 0

    for commission_name, events in all_events.items():
        total_original += len(events)
        filtered_events = filter_events_by_current_week(events)

        if filtered_events:  # Only include commissions that have events in target week
            filtered_all_events[commission_name] = filtered_events
            total_filtered += len(filtered_events)
        else:
            print(f"No events in target week for commission: {commission_name}")

    print(f"Filtered {total_filtered}/{total_original} events from {len(filtered_all_events)}/{len(all_events)} commissions")
    return filtered_all_events
    
    
class Neo4jIntegration:
    def __init__(self, uri, username, password):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self):
        self.driver.close()

    def create_calendar_structure(self):
        """Create the main Calendar node if it doesn't exist"""
        with self.driver.session() as session:
            session.execute_write(self._create_calendar_node)

    def _create_calendar_node(self, tx):
        query = """
        MERGE (cal:Calendar {name: 'Parliamentary Calendar'})
        RETURN cal
        """
        result = tx.run(query)
        return result.single()

    def create_or_get_date_node(self, date_str):
        """Create or get a node for the specified date"""
        with self.driver.session() as session:
            return session.execute_write(self._create_or_get_date_node, date_str)

    def _create_or_get_date_node(self, tx, date_str):
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = date_obj.strftime("%A")

        query = """
        MATCH (cal:Calendar {name: 'Parliamentary Calendar'})
        MERGE (date:Date {date: $date_str, weekday: $weekday})
        MERGE (cal)-[:HAS_DATE]->(date)
        RETURN date
        """
        result = tx.run(query, date_str=date_str, weekday=weekday)
        return result.single()

    def create_or_get_source_node(self, source_name, date_str):
        """Create or get a node for the Calendar_Source with Senato type"""
        with self.driver.session() as session:
            query = """
            MATCH (date:Date {date: $date_str})
            MERGE (source:Calendar_Source {name: $source_name})
            SET source.type = 'Senato' 
            MERGE (date)-[:HAS_SOURCE]->(source)
            RETURN source
            """
            result = session.run(query, 
                               source_name=source_name, 
                               date_str=date_str)
            return result.single()

    def check_if_event_exists(self, source_name, date_str, start_time, title, description):
        """Check if an event with the same key properties already exists"""
        with self.driver.session() as session:
            return session.execute_read(self._check_if_event_exists, source_name, date_str, start_time, title, description)

    def _check_if_event_exists(self, tx, source_name, date_str, start_time, title, description):
        query = """
        MATCH (source:Calendar_Source {name: $source_name})-[:HAS_EVENT]->(event:Event)
        WHERE event.date = $date_str 
        AND event.start_time = $start_time 
        AND event.title = $title
        AND event.description = $description
        RETURN count(event) > 0 as exists
        """
        result = tx.run(query, 
                      source_name=source_name, 
                      date_str=date_str, 
                      start_time=start_time,
                      title=title,
                      description=description)
        record = result.single()
        return record and record["exists"]

    def create_event_node(self, event_data):
        """Create an event node and connect it to the Calendar_Source"""
        with self.driver.session() as session:
            return session.execute_write(self._create_event_node, event_data)

    def _create_event_node(self, tx, event_data):
        # Extract data from event
        source_name = event_data.get("Source", "")
        date_str = event_data.get("Date", "")
        title = event_data.get("Title", "")
        description = event_data.get("Description", "")
        start_time = event_data.get("StartTime", "")
        end_time = event_data.get("EndTime", "")
        topic = event_data.get("Topic", "")
        details = event_data.get("details", "")
        event_type = event_data.get("Type", "")
        url = event_data.get("URL", "")

        query = """
        MATCH (source:Calendar_Source {name: $source_name})
        CREATE (event:Event {
            date: $date_str,
            title: $title,
            description: $description,
            start_time: $start_time,
            end_time: $end_time,
            topic: $topic,
            details: $details,
            type: $event_type,
            url: $url,
            created_at: datetime()
        })
        CREATE (source)-[:HAS_EVENT]->(event)
        RETURN event
        """

        result = tx.run(query, 
                      source_name=source_name,
                      date_str=date_str,
                      title=title,
                      description=description,
                      start_time=start_time,
                      end_time=end_time,
                      topic=topic,
                      details=details,
                      event_type=event_type,
                      url=url)

        return result.single()

    def batch_sync_events(self, events, batch_size=10):
        """Sync events to Neo4j in batches - FIXED VERSION"""
        if not events:
            return 0

        total_events = len(events)
        added_count = 0
        error_count = 0

        # Create the calendar structure first
        self.create_calendar_structure()

        # Get target week for validation
        target_week_start, target_week_end = get_next_monday_friday()

        print(f"Syncing {total_events} Senato events for target week: {target_week_start} to {target_week_end}")

        # Process in batches
        for i in range(0, total_events, batch_size):
            batch = events[i:i + batch_size]
            print(f"Processing batch {i//batch_size + 1}/{(total_events + batch_size - 1)//batch_size} ({len(batch)} events)")

            for event in batch:
                source_name = event.get("Source", "")
                date_str = event.get("Date", "")
                title = event.get("Title", "")
                description = event.get("Description", "")
                start_time = event.get("StartTime", "")

                # CRITICAL FIX: Validate the date is in target range
                try:
                    event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if not (target_week_start <= event_date <= target_week_end):
                        print(f"WARNING: Event date {date_str} is outside target week {target_week_start} to {target_week_end}")
                        print(f"Skipping event: {title}")
                        continue
                except ValueError:
                    print(f"ERROR: Invalid date format '{date_str}' for event: {title}")
                    continue

                # Check if event already exists
                exists = self.check_if_event_exists(source_name, date_str, start_time, title, description)

                if not exists:
                    # Create date node if needed
                    self.create_or_get_date_node(date_str)

                    # Create Calendar_Source node if needed
                    self.create_or_get_source_node(source_name, date_str)

                    # Create the event
                    try:
                        self.create_event_node(event)
                        added_count += 1
                        print(f"✓ Added event: {event.get('Title', 'Event')} on {event.get('Date', '')}")
                    except Exception as e:
                        error_count += 1
                        print(f"✗ Error adding event: {str(e)}")
                else:
                    print(f"⚠ Skipping duplicate event: {event.get('Title', 'Event')} on {event.get('Date', '')}")

                # Small delay between operations
                time.sleep(0.1)

            # Longer delay between batches
            time.sleep(0.5)
            print(f"Batch complete. Added {added_count} events so far.")

        print(f"Sync completed: Added {added_count} events ({error_count} errors)")
        return added_count

    def sync_events_to_neo4j(self, events):
        """Sync events to Neo4j database"""
        print(f"Syncing {len(events)} events to Neo4j...")
        added_count = self.batch_sync_events(events)
        print(f"Sync completed: Added {added_count} events")
        return added_count

def scrape_commission_calendar(url, commission_name):
    """
    Scrape a commission calendar page and return a list of events
    """
    print(f"Scraping {url}...")

    try:
        # Send request to the website with browser-like headers
        headers = {
            "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
            "Accept":
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Connection": "keep-alive"
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract date range and parse the actual month/year
        date_range = None
        calendar_year = datetime.now().year
        calendar_month = datetime.now().month

        for div in soup.select('.centered i'):
            text = div.text.strip()
            if 'settimana dal' in text:
                date_range = text
                print(f"Found date range: {date_range}")

                # Try to extract date from the text
                # Look for patterns like "settimana dal 30 giugno al 6 luglio 2025"
                import re

                # Italian month names mapping
                italian_months = {
                    'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4,
                    'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
                    'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12
                }

                # Extract start date from the range
                # Pattern: "settimana dal DD MONTH" or "settimana dal DD MONTH al DD MONTH YYYY"
                start_match = re.search(r'settimana dal (\d+) (\w+)', text.lower())
                year_match = re.search(r'(\d{4})', text)

                if start_match:
                    start_day = int(start_match.group(1))
                    start_month_name = start_match.group(2)

                    if start_month_name in italian_months:
                        calendar_month = italian_months[start_month_name]
                        print(f"Extracted month: {calendar_month} ({start_month_name})")

                if year_match:
                    calendar_year = int(year_match.group(1))
                    print(f"Extracted year: {calendar_year}")

                break

        print(f"Commission: {commission_name}")
        print(f"Period: {date_range or 'Unknown'}")
        print(f"Using calendar date: {calendar_year}-{calendar_month:02d}")

        # Extract calendar entries
        events = []

        # Find all tables with calendar data
        tables = soup.select('table.csc-table')

        # Process each table
        for table in tables:
            # Process each row in the table
            current_day = None
            current_day_num = None

            for row in table.select('tr'):
                # Get the day column if it exists in this row
                day_col = row.select_one('.day-column')

                # If this row has a day column, update the current day
                if day_col:
                    day_text = day_col.text.strip()
                    day_match = re.search(r'([A-Za-z]+)\s+(\d+)', day_text)

                    if day_match:
                        current_day = day_match.group(1)
                        current_day_num = day_match.group(2)

                # Only process rows that have time data
                time_col = row.select_one('.time-column')
                if not time_col:
                    continue

                # Extract time
                time_text = time_col.text.strip()
                time_match = re.search(r'(\d+:\d+)', time_text)
                time_value = time_match.group(1) if time_match else ""

                # Extract structure
                structure_col = row.select_one('.sottostruttura-column')
                structure_text = ""
                if structure_col:
                    structure_text = structure_col.get_text(strip=True,
                                                            separator=" ")

                # Extract content
                content_col = row.select_one(
                    '.views-field-field-testo-convocazione')
                content_text = ""

                if content_col:
                    # Get the text content
                    content_text = content_col.get_text(strip=True,
                                                        separator=" ")

                    # Extract links from content and make them part of the text
                    for a_tag in content_col.select('a'):
                        href = a_tag.get('href', '')
                        link_text = a_tag.text.strip()

                        # Convert relative URLs to absolute
                        if href.startswith('/'):
                            href = f"https://www.senato.it{href}"

                        # Replace the link with text format that includes URL
                        a_tag.replace_with(f"{link_text} ({href})")

                    # Get updated content text with inline links
                    content_text = content_col.get_text(strip=True,
                                                        separator=" ")

                # Skip if we don't have the basic required data
                if not current_day or not current_day_num or not time_value:
                    continue

                # Create a descriptive text combining structure and content
                description = f"{structure_text}\n\n{content_text}".strip()

                # Create a formatted date using target week context
                day = int(current_day_num)

                # FIXED: Use target week context for proper date calculation
                target_week_start, _ = get_next_monday_friday()
                target_year = target_week_start.year
                target_month = target_week_start.month

                # Try using target month first
                result_date = datetime(target_year, target_month, day).date()

                # If date is way off from target week, try adjacent months
                week_end = target_week_start + timedelta(days=6)
                if result_date < target_week_start - timedelta(days=10):
                    if target_month == 12:
                        result_date = datetime(target_year + 1, 1, day).date()
                    else:
                        result_date = datetime(target_year, target_month + 1, day).date()
                elif result_date > week_end + timedelta(days=10):
                    if target_month == 1:
                        result_date = datetime(target_year - 1, 12, day).date()
                    else:
                        result_date = datetime(target_year, target_month - 1, day).date()

                date_str = result_date.strftime("%Y-%m-%d")

                # Create event
                event = {
                    "Source": commission_name,
                    "Date": date_str,
                    "Time": time_value,
                    "URL": url,
                    "Description": description
                }

                events.append(event)

        print(f"Found {len(events)} calendar entries")
        return events

    except Exception as e:
        print(f"Error: {e}")
        return []


def extract_commission_urls(
        overview_url="https://www.senato.it/CLS/pub/quadro/permanenti-giunte"):
    """Extract all commission URLs from the Senate overview page"""

    print(f"Fetching overview page: {overview_url}")

    # Send request to the website with browser-like headers
    headers = {
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
        "Accept":
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Connection": "keep-alive"
    }

    try:
        response = requests.get(overview_url, headers=headers)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find all tables with the commission information
        # Looking for tables inside div.bordoNero
        tables = soup.select("div.bordoNero table")

        print(f"Found {len(tables)} tables with commission information")

        commission_urls = {}

        # Process each table
        for table_idx, table in enumerate(tables):
            print(f"\nProcessing table {table_idx + 1}:")

            # Get the table caption if available
            caption = table.find("caption")
            table_title = caption.text.strip(
            ) if caption else f"Table {table_idx + 1}"
            print(f"Table title: {table_title}")

            # Find all rows in the table body
            rows = table.select("tbody tr")

            # Process each row
            for row_idx, row in enumerate(rows):
                # Skip rows that don't contain commission info (like empty rows)
                if not row.find("th"):
                    continue

                # Get the commission name from the first th element
                commission_name = row.find("th").text.strip()

                # Find the link to the commission's convocations
                link_cell = row.find("td")
                link = None

                if link_cell:
                    link_element = link_cell.find("a")
                    if link_element and "href" in link_element.attrs:
                        link = link_element["href"]

                if link:
                    # Convert relative URL to absolute
                    if link.startswith("/"):
                        full_url = f"https://www.senato.it{link}"
                    else:
                        full_url = link

                    # Add to our dictionary
                    commission_urls[commission_name] = full_url
                    print(f"  {row_idx + 1}. {commission_name} → {full_url}")

        return commission_urls

    except Exception as e:
        print(f"Error fetching or parsing the overview page: {e}")
        return {}



def process_commission_events_with_gpt4o(commission_name, events):
    """Process all events for a commission to determine summaries, start times, end times, and details"""
    if not events or len(events) == 0:
        print(f"No events to process for {commission_name}")
        return events

    try:
        # Create a copy of events with added IDs
        events_with_ids = []
        for i, event in enumerate(events):
            event_copy = event.copy()
            event_copy["id"] = f"event_{i}"
            events_with_ids.append(event_copy)

        # Sort events by date and time for proper processing
        events_with_ids.sort(key=lambda x: (x["Date"], x["Time"]))

        # Initialize OpenAI client
        openai_client = openai.OpenAI(api_key=get_openai_api_key())

        # Format events for the prompt
        events_text = json.dumps(events_with_ids, indent=2, ensure_ascii=False)
        print(f"INPUT FOR LLM: {events_text}")
        print(f"Processing {len(events)} events for {commission_name}...")

        user_prompt = events_text

        prompt_file_path = 'Prompt/SenatoEvents.yaml'
        replacements = {"user_prompt": user_prompt}
        system_prompt, user_prompt, model_params = extract_prompts(
            prompt_file_path, **replacements)
        print("---" * 30)
        print(
            f"SENATO system_prompt: {system_prompt}, user_prompt: {user_prompt}, model_params: {model_params}"
        )
        print("---" * 30)

        # Send request to GPT-4o with backoff retry logic
        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            response = openai_client.chat.completions.create(
                model=model_params['name'],  # Or your specific model
                response_format={"type": "json_object"},
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
                temperature=model_params['temperature'],
                store=True,
                metadata={
                    "project": "CZP Calendar",
                    "agent": "Senato"
                })

            # Extract response
            result = response.choices[0].message.content.strip()
            print(f"result from GPT4.1:\n\n{result}\n")
            print(f"GPT-4.1 response received (length: {len(result)})")

            # If empty response, retry
            if not result:
                print(
                    f"Received empty response. Retrying ({attempt+1}/{max_retries})..."
                )
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue

            # Parse the response
            try:
                data = json.loads(result)
                print(
                    f"DEBUG: Parsed JSON data with {len(data.get('events', []))} events"
                )

            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {e}")
                print(f"Raw response: '{result}'")
                if attempt < max_retries - 1:
                    print(f"Retrying ({attempt+1}/{max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return events

            # Extract events array from the response
            if "events" in data and isinstance(data["events"], list):
                event_infos = data["events"]
                print(
                    f"DEBUG: Processing {len(event_infos)} events from GPT-4.1 output"
                )

                # Process the GPT-4o generated events to create our final event list
                processed_events = []

                # Group events by original event ID (event_0, event_1, etc.)
                event_groups = {}
                for info in event_infos:
                    base_id = info.get("id",
                                       "").split("_")[0] + "_" + info.get(
                                           "id", "").split("_")[1]
                    if "_" in info.get("id", "") and len(
                            info.get("id", "").split("_")) > 2:
                        base_id = info.get("id",
                                           "").split("_")[0] + "_" + info.get(
                                               "id", "").split("_")[1]
                    else:
                        base_id = info.get("id", "")

                    if base_id not in event_groups:
                        event_groups[base_id] = []
                    event_groups[base_id].append(info)

                # Create events based on original input data plus the enriched information
                for i, event in enumerate(events):
                    event_id = f"event_{i}"

                    if event_id in event_groups:
                        # For each sub-event, create a new event based on the original
                        for sub_event in event_groups[event_id]:
                            new_event = event.copy()
                            new_event["Title"] = sub_event.get("title", "")
                            new_event["StartTime"] = event[
                                "Time"]  # Use original time
                            new_event["EndTime"] = sub_event.get(
                                "end_time", "")
                            new_event["details"] = sub_event.get("details", "")
                            new_event["Topic"] = sub_event.get("topic", "")

                            processed_events.append(new_event)
                    else:
                        # If no match found (shouldn't happen), use default values
                        default_event = event.copy()
                        default_event["Summary"] = "Event"
                        default_event["StartTime"] = event["Time"]
                        default_event["EndTime"] = ""
                        default_event["details"] = ""
                        processed_events.append(default_event)

                return processed_events

            # Return original events if we couldn't process properly
            return events

    except Exception as e:
        print(f"Error processing events with GPT-4o: {e}")
        print(f"Error details: {traceback.format_exc()}")
        return events  # Return original events if there's an error


def load_processed_data(
        filename="processed_data/all_commissions_processed.json"):
    """Load processed commission data from JSON file"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: File {filename} not found")
        return {}
    except json.JSONDecodeError:
        print(f"Error: File {filename} contains invalid JSON")
        return {}


def flatten_events(commission_data):
    """Flatten nested commission data into a list of events"""
    all_events = []
    for commission_name, events in commission_data.items():
        for event in events:
            # Make sure each event has all required fields
            if "Summary" not in event:
                event["Summary"] = ""
            if "StartTime" not in event:
                event["StartTime"] = event.get("Time", "")
            if "EndTime" not in event:
                event["EndTime"] = ""
            if "Type" not in event:
                event["Type"] = ""
            if "details" not in event:
                event["details"] = ""

            all_events.append(event)

    return all_events


def senato_main():
    """Main function to extract and save all commission calendars"""
    promptDownloader()
    # Extract commission URLs
    commission_urls = extract_commission_urls()

    call_webhook_with_success(payload.get('id'),{
        "status": "inprogress",
        "data": {
            "title": f"Extracting the URLs from the actual resource",
            "info": "Processing",
        },
    })

    if not commission_urls:
        print("No commission URLs found")
        return

    # Dictionary to hold all events by commission
    all_events = {}

    # Process each commission
    for commission_name, url in commission_urls.items():
        # Extract events for this commission
        call_webhook_with_success(payload.get('id'),{
            "status": "inprogress",
            "data": {
                "title": f"Process each commission in senato",
                "info": "Processing",
            },
        })

        events = scrape_commission_calendar(url, commission_name)

        call_webhook_with_success(payload.get('id'),{
            "status": "inprogress",
            "data": {
                "title": f"Extracting the senato events from the actual resource",
                "info": "Processing",
            },
        })

        # Add to our dictionary
        all_events[commission_name] = events

        # Be nice to the server
        time.sleep(1)

    # Create output directory
    os.makedirs("raw_data", exist_ok=True)

    # Save all data to JSON file
    with open("raw_data/all_commissions_raw.json", "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)

    print(f"Saved all commission data to raw_data/all_commissions_raw.json")

    call_webhook_with_success(payload.get('id'),{
        "status": "inprogress",
        "data": {
            "title": f"Extraction is completed and stored in a json",
            "info": "Processing",
        },
    })

    # Print summary
    total_events = sum(len(events) for events in all_events.values())
    print(f"\nTotal commissions: {len(all_events)}")
    print(f"Total events: {total_events}")

    # Neo4j Configuration 
    neo4j_uri = "neo4j+s://c94a0c28.databases.neo4j.io"
    neo4j_username = "neo4j"
    neo4j_password = "W0pumaSXNH7U2ZfsNPl4gB1tS4Iw1e-79LbKD7e05fk"

    # Load raw data
    print("Loading raw commission data...")
    try:
        with open("raw_data/all_commissions_raw.json", "r", encoding="utf-8") as f:
            all_commissions = json.load(f)
    except FileNotFoundError:
        print("Error: Raw data file not found. Please run step1_scrape.py first.")
        return

    call_webhook_with_success(payload.get('id'),{
        "status": "inprogress",
        "data": {
            "title": f"Working on the Neo4j DB now.",
            "info": "Processing",
        },
    })

    # Initialize Neo4j connection
    neo4j = Neo4jIntegration(neo4j_uri, neo4j_username, neo4j_password)

    # Create output directory for processed data
    os.makedirs("processed_data/commissions", exist_ok=True)

    # Track all processed events
    all_processed_events = {}
    total_synced = 0

    try:
        # Process each commission one by one
        for commission_name, events in all_commissions.items():
            print(f"\n--- Processing {commission_name} ({len(events)} events) ---")

            call_webhook_with_success(payload.get('id'),{
                "status": "inprogress",
                "data": {
                    "title": f"Storing content to the Neo4j DB process is about to begin",
                    "info": "Processing",
                },
            })

            # Filter out 10:00 Assemblea events before processing
            filtered_events = []
            for event in events:
                # Skip Assemblea events at 10:00
                if (event.get("Time") == "10:00" and event.get("Description", "").startswith("Assemblea (n.")):
                    print(f"Skipping Assemblea event: {event.get('Description')}")
                    continue

                # Skip SCONVOCATA events
                if "SCONVOCATA" in event.get("Description", ""):
                    print(f"Skipping SCONVOCATA event: {event.get('Description')}")
                    continue

                filtered_events.append(event)

            print(f"Filtered out {len(events) - len(filtered_events)} Assemblea/SCONVOCATA events")
            events = filtered_events

            call_webhook_with_success(payload.get('id'),{
                "status": "inprogress",
                "data": {
                    "title": f"Extracting the events using GPT4.1",
                    "info": "Processing",
                },
            })

            # Step 1: Process this commission's events with GPT-4o
            processed_events = process_commission_events_with_gpt4o(commission_name, events)

            call_webhook_with_success(payload.get('id'),{
                "status": "inprogress",
                "data": {
                    "title": f"Events are extracted for that commission.",
                    "info": "Processing",
                },
            })

            # Print summary of the processing
            original_count = len(events)
            processed_count = len(processed_events)
            print(f"Processed {original_count} input events into {processed_count} output events")

            if processed_count > original_count:
                print(f"Split {processed_count - original_count} complex events into multiple entries")

            # Step 2: Immediately sync these events to Neo4j
            print(f"Syncing {len(processed_events)} events for {commission_name} to Neo4j...")
            call_webhook_with_success(payload.get('id'),{
                "status": "inprogress",
                "data": {
                    "title": f"Syncing to Neo4j",
                    "info": "Processing",
                },
            })

            added_count = neo4j.batch_sync_events(processed_events)
            total_synced += added_count

            # Step 3: Save the processed events to a file (for backup)
            safe_name = commission_name.split("(")[0].strip()
            safe_name = re.sub(r'[^\w\s-]', '', safe_name)
            safe_name = re.sub(r'[-\s]+', '_', safe_name)

            with open(f"processed_data/commissions/{safe_name}.json", "w", encoding="utf-8") as f:
                json.dump(processed_events, f, ensure_ascii=False, indent=2)

            # Save to the combined data
            all_processed_events[commission_name] = processed_events

            call_webhook_with_success(payload.get('id'),{
                "status": "inprogress",
                "data": {
                    "title": f"Save all senato events in processed json",
                    "info": "Processing",
                },
            })

            print(f"Completed processing {commission_name}. Added {added_count} events to Neo4j.")

            # Save the combined data periodically
            with open("processed_data/all_commissions_processed.json", "w", encoding="utf-8") as f:
                json.dump(all_processed_events, f, ensure_ascii=False, indent=2)

        print(f"\nProcess complete! Processed {len(all_processed_events)} commissions")
        print(f"Added {total_synced} events to Neo4j")

    finally:
        # Ensure Neo4j connection is closed properly
        neo4j.close()

    return "Senato Is Done"