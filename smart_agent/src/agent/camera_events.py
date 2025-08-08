import requests
from bs4 import BeautifulSoup
import json
from ..utils.webhook import call_webhook_with_error, call_webhook_with_success

import urllib.parse
import re
import os
import csv
import json
import os
import time
from openai import OpenAI
from .prompt_extract import extract_prompts
from .get_prompt_from_git import main as promptDownloader
from neo4j import GraphDatabase
from datetime import datetime, timedelta

# Initialize OpenAI client with API key from environment
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)




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
    """Check if a given date string (YYYY-MM-DD format) falls within the current week."""
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

    print(
        f"Filtered {len(filtered_events)} events (skipped {skipped_count} outside current week)"
    )
    return filtered_events


def debug_date_filtering(events):
    """Debug function to see what's going wrong with date filtering"""
    print("=== DATE FILTERING DEBUG ===")

    # Show current week range
    from datetime import datetime, timedelta
    today = datetime.now().date()
    start_date, end_date = get_next_monday_friday()
    print(f"Today: {today}")
    print(f"Current week range: {start_date} to {end_date}")
    print(f"Today's weekday: {today.weekday()} (0=Monday, 6=Sunday)")

    # Show sample event dates
    print(f"\nSample event dates (first 10):")
    for i, event in enumerate(events[:10]):
        event_date = event.get('Date', 'NO DATE')
        print(
            f"Event {i+1}: Date='{event_date}', Entity='{event.get('entity', 'Unknown')}'"
        )

        # Try to parse the date
        if event_date:
            try:
                parsed_date = datetime.strptime(event_date, "%Y-%m-%d").date()
                in_range = start_date <= parsed_date <= end_date
                print(f"  -> Parsed as: {parsed_date}, In range: {in_range}")
            except Exception as e:
                print(f"  -> Parse error: {e}")

    # Check unique dates
    unique_dates = set()
    for event in events:
        date_str = event.get('Date', '')
        if date_str:
            unique_dates.add(date_str)

    print(f"\nAll unique dates found in events:")
    for date_str in sorted(unique_dates):
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            in_range = start_date <= parsed_date <= end_date
            print(f"  {date_str} -> {parsed_date} (In range: {in_range})")
        except Exception as e:
            print(f"  {date_str} -> Parse error: {e}")

    print("=== END DEBUG ===\n")


def filter_grouped_events_by_current_week(grouped_events):
    """Filter grouped events (dictionary format) to only include current week events."""
    if not grouped_events:
        return {}

    start_date, end_date = get_next_monday_friday()
    print(f"Filtering grouped events for week: {start_date} to {end_date}")

    filtered_grouped = {}
    total_original = 0
    total_filtered = 0

    for source_name, events in grouped_events.items():
        total_original += len(events)
        filtered_events = filter_events_by_current_week(events)

        if filtered_events:  # Only include sources that have events in current week
            filtered_grouped[source_name] = filtered_events
            total_filtered += len(filtered_events)
        else:
            print(f"No events in current week for source: {source_name}")

    print(
        f"Filtered {total_filtered}/{total_original} events from {len(filtered_grouped)}/{len(grouped_events)} sources"
    )
    return filtered_grouped


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
        print(f"DEBUG: Creating/getting date node for '{date_str}'")

        with self.driver.session() as session:
            return session.execute_write(self._create_or_get_date_node, date_str)

    def _create_or_get_date_node(self, tx, date_str):
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            weekday = date_obj.strftime("%A")

            print(f"DEBUG: Parsed '{date_str}' as {date_obj}, weekday: {weekday}")

            query = """
            MATCH (cal:Calendar {name: 'Parliamentary Calendar'})
            MERGE (date:Date {date: $date_str, weekday: $weekday})
            MERGE (cal)-[:HAS_DATE]->(date)
            RETURN date
            """
            result = tx.run(query, date_str=date_str, weekday=weekday)
            return result.single()

        except ValueError as e:
            print(f"ERROR: Could not parse date '{date_str}': {e}")
            return None

    def create_or_get_source_node(self, source_name, date_str):
        """Create or get a node for the Calendar_Source with Camera type"""
        print(f"DEBUG: Creating/getting source '{source_name}' for date '{date_str}'")

        with self.driver.session() as session:
            query = """
            MATCH (date:Date {date: $date_str})
            MERGE (source:Calendar_Source {name: $source_name})
            SET source.type = 'Camera' 
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
        details = event_data.get("Details", "")
        event_type = event_data.get("EventType", event_data.get("Type", ""))
        url = event_data.get("URL", "")
        summary = event_data.get("Summary", "")

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
            summary: $summary,
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
                        url=url,
                        summary=summary)

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

        print(f"Syncing {total_events} events for target week: {target_week_start} to {target_week_end}")

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

                print(f"DEBUG: Processing event '{title}' with date '{date_str}'")

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
                    # Create date node using the EVENT'S actual date
                    self.create_or_get_date_node(date_str)

                    # Create Calendar_Source node connected to the CORRECT date
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

def scrape_camera_schedule(api_token="2bb56bfb-58ce-4bfe-a945-61123158cde6"):
    """Main function to scrape the weekly schedule, detailed meeting information, and calendar"""
    print("Starting scraping...")

    # Base URL
    base_url = "https://www.camera.it/leg19/"
    headers = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        # Get the main page
        main_url = base_url + "76"
        print(f"Requesting main page: {main_url}")
        response = requests.get(main_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the settimanali tab link to get its URL
        settimanali_tab = soup.select_one("li.settimana a")
        if not settimanali_tab:
            print("Could not find the settimanali tab link.")
            return []

        # Get the URL for the settimanali tab and ensure it's absolute
        href = settimanali_tab.get('href', '')
        settimanali_url = urllib.parse.urljoin(main_url, href)
        print(f"Found settimanali tab URL: {settimanali_url}")

        # Get the settimanali page content
        settimanali_response = requests.get(settimanali_url, headers=headers)
        settimanali_response.raise_for_status()
        settimanali_soup = BeautifulSoup(settimanali_response.text,
                                         'html.parser')

        # Process all tables in the settimanali tab
        all_data = []
        tables = settimanali_soup.select('table.tabellaXHTML')
        print(f"Found {len(tables)} tables")

        # Create output directory
        os.makedirs("output", exist_ok=True)

        for table_index, table in enumerate(tables):
            print(f"Processing table {table_index+1}/{len(tables)}")
            # TEMPORARILY use debug version:
            debug_process_table_dates(table, base_url)

            table_data = process_table(table, base_url)
            all_data.extend(table_data)

        call_webhook_with_success({
            "status": "inprogress",
            "data": {
                "title": f"Processing the camera extraction",
                "info": "Processing",
            },
        })

        # Now fetch details for each meeting URL
        all_data = fetch_meeting_details(all_data, headers, base_url)

        # Format dates to yyyy-mm-dd format
        all_data = format_dates(all_data)

        # Now find the calendar tab URL from the main page
        calendario_url = find_calendario_url(soup, main_url)

        # Now scrape the calendar page using the Web Scraper API Proxy
        if calendario_url:
            calendar_data = scrape_calendar_page_with_proxy(
                calendario_url, api_token)
            all_data.extend(calendar_data)
            print(
                f"Found {len(all_data)} entries total ({len(calendar_data)} from calendar)"
            )
        else:
            print(
                f"Found {len(all_data)} entries total (none from calendar - URL not found)"
            )

        return all_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching page: {e}")
        return []


def find_calendario_url(soup, base_url):
    """Find the URL for the Calendario tab"""
    # Look specifically for the "mese" class which contains the calendar link
    mese_li = soup.select_one('li.mese')
    if mese_li:
        calendar_link = mese_li.select_one('a')
        if calendar_link:
            href = calendar_link.get('href', '')
            if href:
                calendario_url = urllib.parse.urljoin(base_url, href)
                print(f"Found Calendario tab URL: {calendario_url}")
                return calendario_url

    # Alternative approach - look for any link containing "Calendario" text
    for link in soup.find_all('a'):
        if link.get_text(strip=True) == "Calendario":
            href = link.get('href', '')
            if href:
                calendario_url = urllib.parse.urljoin(base_url, href)
                print(f"Found Calendario link by text: {calendario_url}")
                return calendario_url

    # If we can't find it, try a direct URL based on the HTML structure provided
    direct_url = f"{base_url}76?active_tab_3806=4184"
    print(f"Could not find Calendario tab, using direct URL: {direct_url}")
    return direct_url


def scrape_calendar_page_with_proxy(calendar_url, api_token):
    """Scrape the calendar page using Web Scraper API Proxy with JS rendering enabled"""
    print("Scraping calendar page using Web Scraper API Proxy...")
    results = []

    try:
        # Configure the API endpoint
        api_url = "https://scraper-proxy-usama14.replit.app/api/scrape"  # Adjust if needed

        print(
            f"Requesting calendar page via API proxy with JS rendering: {calendar_url}"
        )

        # Set up parameters for the API request
        params = {
            "api_key": api_token,
            "url": calendar_url,
            "render": True,
            "keep_headers": "1"
        }

        # Make the request to the API proxy
        calendar_response = requests.get(api_url, params=params)
        calendar_response.raise_for_status()

        # Save the HTML for debugging
        calendar_html = calendar_response.text
        # with open("calendar_page.html", "w", encoding="utf-8") as f:
        #     f.write(calendar_html)
        # print(f"Saved calendar page HTML to calendar_page.html for debugging")

        # Parse the HTML
        calendar_soup = BeautifulSoup(calendar_html, 'html.parser')

        # Find the calendar table
        calendar_table = calendar_soup.select_one('table.calendario_punti')

        if not calendar_table:
            print(
                "Could not find table.calendario_punti - trying alternative selectors..."
            )

            # Try other selectors that might match the calendar table
            selectors = [
                '.calendario_container table', 'div.calendario table',
                'table.time', 'div[id^="calendario"] ~ table',
                '#container_4184 table',
                'div.calendario_container table.calendario_punti'
            ]

            for selector in selectors:
                tables = calendar_soup.select(selector)
                if tables:
                    print(
                        f"Found {len(tables)} tables with selector: {selector}"
                    )
                    calendar_table = tables[0]
                    break

        if not calendar_table:
            # Last resort: Find any table with calendar content
            print("Trying to find any table with calendar-like content...")
            all_tables = calendar_soup.find_all('table')
            print(f"Found {len(all_tables)} tables total")

            for i, table in enumerate(all_tables):
                # Check if the table contains date-like text
                table_text = table.get_text()
                if re.search(
                        r'(\d+\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre))|(?:lunedì|martedì|mercoledì|giovedì|venerdì)',
                        table_text, re.IGNORECASE):
                    calendar_table = table
                    print(
                        f"Selected table {i+1} as likely calendar table based on content"
                    )
                    break

        if not calendar_table:
            print("Could not find the calendar table in the proxied response.")
            return results

        # Extract calendar metadata
        calendar_info = {'title': '', 'period': '', 'protocol': ''}

        title_elem = calendar_soup.select_one(
            '.calendario .titolo, .calendario_container .titolo')
        if title_elem:
            calendar_info['title'] = title_elem.get_text(strip=True)

        period_elem = calendar_soup.select_one(
            '.calendario .calendario_periodo, .calendario_container .calendario_periodo'
        )
        if period_elem:
            calendar_info['period'] = period_elem.get_text(strip=True)

        protocol_elem = calendar_soup.select_one(
            '.calendario .calendario_protocollo, .calendario_container .calendario_protocollo'
        )
        if protocol_elem:
            calendar_info['protocol'] = protocol_elem.get_text(strip=True)

        print(f"Calendar info: {calendar_info}")

        # Process each row in the calendar table
        rows = calendar_table.select('tr')
        print(f"Found {len(rows)} rows in the calendar table")

        for i, row in enumerate(rows):
            # Get all cells in the row
            cells = row.find_all('td')

            # Skip if no cells
            if not cells:
                continue

            # Get date information - typically in the first cell with class "ventiX100"
            date_cell = row.select_one(
                'td.ventiX100') or cells[0] if cells else None
            date_value = ""
            time_value = ""
            day_value = ""

            if date_cell:
                # Extract date and time info
                date_text = date_cell.get_text(strip=True)

                # Try to extract the day of week, date, and time
                # For days of the week in Italian
                day_match = re.search(
                    r'(\b(?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)\b)',
                    date_text, re.IGNORECASE)
                if day_match:
                    day_value = day_match.group(1)

                # For date format like "22 aprile"
                date_match = re.search(
                    r'(\d+\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre))',
                    date_text, re.IGNORECASE)
                if date_match:
                    date_value = date_match.group(1)

                # For time format like "ore 11"
                time_match = re.search(r'(?:ore\s+[\d:,.-]+[^()]*)', date_text,
                                       re.IGNORECASE)
                if time_match:
                    time_value = time_match.group(0)

                # If we couldn't parse specifics, use the whole text
                if not date_value and not day_value:
                    date_value = date_text

            # Get content from second column with class "ottantaX100"
            content_text = ""
            content_cell = row.select_one('td.ottantaX100') or (
                cells[1] if len(cells) > 1 else None)
            if content_cell:
                content_text = content_cell.get_text(strip=True)

            # Store the entire row HTML
            row_html = str(row)

            results.append({
                'entity':
                "Assemblea Camera",
                'entity_url':
                calendar_url,
                'commission_number':
                '',
                'commission_id':
                '',
                'date':
                date_value,
                'day':
                day_value,
                'content':
                "Calendar entry",
                'url':
                calendar_url,
                'calendar_info':
                calendar_info,
                'row_index':
                i + 1,
                'time':
                time_value,
                'content_preview':
                content_text[:100]
                if len(content_text) > 100 else content_text,
                'details': {
                    'html_content': row_html
                }
            })

        print(f"Processed {len(results)} calendar entries")
        return results

    except Exception as e:
        print(f"Error scraping calendar with proxy: {str(e)}")
        import traceback
        traceback.print_exc()
        return results


def process_table(table, base_url):
    """Extract data from a table in the weekly schedule"""
    results = []

    # Get table caption/title if available
    caption = table.find('caption')
    table_title = caption.text.strip() if caption else "Unknown Table"

    # Find all rows
    rows = table.find_all('tr')
    if len(rows) < 3:  # Need header, dates, and at least one data row
        return results

    # Get days of week from headers
    headers = []
    for th in rows[0].find_all('th')[1:]:  # Skip first column (entity name)
        headers.append(th.text.strip())

    # Get dates from second row
    dates = []
    for td in rows[1].find_all('td')[1:]:  # Skip first column
        dates.append(td.text.strip())

    # Process data rows
    for row in rows[2:]:  # Skip header and date rows
        cells = row.find_all('td')

        # Skip rows without enough cells
        if len(cells) <= 1:
            continue

        # Get entity name (first cell)
        entity_cell = cells[0]
        entity_link = entity_cell.find('a')

        if entity_link:
            entity_name = entity_link.text.strip()
            entity_url = urllib.parse.urljoin(base_url,
                                              entity_link.get('href', ''))

            # Extract commission number from the name or URL
            commission_number = extract_commission_number(entity_name)
            commission_id = get_commission_id(commission_number,
                                              entity_url=entity_url)
        else:
            entity_name = entity_cell.text.strip()
            entity_url = ''
            commission_number = extract_commission_number(entity_name)
            commission_id = get_commission_id(commission_number)

        # Skip if no entity name
        if not entity_name:
            continue

        # Process each cell (except first)
        for i, cell in enumerate(cells[1:], 0):
            # Skip empty cells
            link = cell.find('a')
            if not link:
                continue

            # Get corresponding date and day
            date_value = dates[i] if i < len(dates) else ''
            day_value = headers[i] if i < len(headers) else ''

            # Make sure URL is absolute
            url = urllib.parse.urljoin(base_url, link.get('href', ''))

            results.append({
                'entity': entity_name,
                'entity_url': entity_url,
                'commission_number': commission_number,
                'commission_id': commission_id,
                'date': date_value,
                'day': day_value,
                'content': "",
                'url': url,
                'details': {}  # Will be filled later
            })

    return results


def fetch_meeting_details(data, headers, base_url):
    """Fetch detailed information from each meeting URL"""
    print(f"Fetching details for {len(data)} meetings...")

    for index, meeting in enumerate(data):
        # Skip calendar entries which already have details
        if meeting.get('content') == "Calendar entry":
            continue

        url = meeting['url']
        print(f"Fetching details for meeting {index+1}/{len(data)}: {url}")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            # Parse the meeting page
            details = extract_meeting_details(response.text, base_url)
            meeting['details'] = details

            # Update commission ID if we found it in the HTML
            if not meeting['commission_id'] and 'commission_id' in details:
                meeting['commission_id'] = details['commission_id']

        except requests.exceptions.RequestException as e:
            print(f"Error fetching meeting details: {e}")
            meeting['details'] = {"error": str(e)}

    return data


def extract_meeting_details(html_content,
                            base_url="https://www.camera.it/leg19/"):
    """Extract meeting details from a meeting page HTML content"""
    soup = BeautifulSoup(html_content, 'html.parser')

    # Extract commission ID from HTML if present
    commission_id = ""
    commission_input = soup.select_one(
        'input[name="shadow_organo_parlamentare"]')
    if commission_input:
        commission_id = commission_input.get('value', '')

    # Find the main table with meeting details
    table = soup.find('table', class_='tabellaXHTML')
    if not table:
        return {
            "error": "No meeting details table found",
            "commission_id": commission_id
        }

    # Initialize details with a consistent structure
    details = {
        "title": "",  # Commission title 
        "full_title": "",  # Full title with area
        "date": "",  # Full date
        "commission_id": commission_id,  # Store the ID we found
        "items": []  # List of agenda items
    }

    # Extract title and commission name
    title_row = table.find('tr')
    if title_row:
        title_cell = title_row.find('td')
        if title_cell:
            strong_tag = title_cell.find('strong')
            em_tag = title_cell.find('em')

            if strong_tag:
                details["title"] = strong_tag.get_text(strip=True)

            if em_tag:
                area = em_tag.get_text(strip=True)
                details["full_title"] = f"{details['title']} {area}"

    # Extract date
    date_row = table.find('tr', class_='dataconvocazione')
    if date_row:
        details["date"] = date_row.get_text(strip=True)

    # Store all rows for processing
    rows = table.find_all('tr')

    # Process all rows to identify sections and create agenda items
    items = []
    current_item = None
    sub_items = []

    # Skip the first 4 rows (commission name, empty row, date, empty row)
    for i in range(4, len(rows)):
        row = rows[i]
        cells = row.find_all('td')

        if len(cells) != 2:
            continue  # Skip if not 2 cells

        left_text = cells[0].get_text(strip=True)
        right_text = cells[1].get_text(strip=True)

        # Skip empty rows
        if not left_text and not right_text:
            continue

        # Check if this starts a new agenda item
        is_new_time = re.match(r'^Ore\s+(\d+[,\.:]\d+|\d+)$', left_text)
        is_al_termine = left_text == "Al termine"
        is_avviso = left_text == "AVVISO"

        # Create a new agenda item for time entries or "Al termine"
        if is_new_time or is_al_termine:
            # Save the previous item if it exists
            if current_item:
                current_item["sub_items"] = sub_items
                items.append(current_item)

            # Create new item
            time_value = left_text.replace("Ore ",
                                           "") if is_new_time else left_text
            time_value = time_value.replace(',', '.').replace(
                ':', '.') if is_new_time else time_value

            # Determine the type (right cell for time entries)
            item_type = right_text if right_text.startswith(
                ("SEDE", "COMMISSIONI", "UFFICIO")) else ""

            current_item = {
                "time": time_value,
                "location": right_text if not item_type else "",
                "type": item_type,
                "section": "",
                "secondary_type": "",
                "sub_items": []
            }

            sub_items = []  # Reset sub-items for new agenda item

        # Handle notices
        elif is_avviso:
            if "notices" not in details:
                details["notices"] = []
            details["notices"].append(right_text)

        # Handle section identifiers and secondary types
        elif left_text and not is_new_time and not is_avviso and current_item:
            # If this has a section but isn't a new time entry, it might be a section identifier
            if current_item and not current_item["section"]:
                current_item["section"] = left_text

            # Check for secondary type in right cell
            if right_text.startswith(("AUDIZIONI", "SEDE")):
                current_item["secondary_type"] = right_text
            else:
                # This is a sub-item (or part of one)
                process_sub_item(cells[1], sub_items, base_url)

        # Process sub-items
        elif right_text and current_item:
            process_sub_item(cells[1], sub_items, base_url)

    # Add the last item
    if current_item:
        current_item["sub_items"] = sub_items
        items.append(current_item)

    # Process the items to handle transitions between meeting types
    processed_items = []
    i = 0

    while i < len(items):
        item = items[i]

        # Check if the next item is an "Al termine" item with a different type
        if i + 1 < len(items) and items[i + 1]["time"] == "Al termine":
            current_item = item.copy()
            processed_items.append(current_item)

            # Start a fresh list of sub_items for each new meeting type
            next_item = items[i + 1]

            # Look for type transitions in Al termine items
            if next_item["type"] and next_item["type"] != current_item["type"]:
                # This is a different meeting type - keep it separate
                i += 1
                continue

            # Combine consecutive "Al termine" items with same type but different sub-items
            if next_item["secondary_type"] != current_item["secondary_type"]:
                # This is a different secondary type - keep it separate
                i += 1
                continue

            # Otherwise, this is a continuation - merge sub-items
            current_item["sub_items"].extend(next_item["sub_items"])
            i += 2
        else:
            processed_items.append(item)
            i += 1

    details["items"] = processed_items

    # Clean up the structure to ensure consistency
    normalize_meeting_details(details)

    return details


def process_sub_item(cell, sub_items, base_url):
    """Extract a sub-item from a table cell and add it to the list"""
    right_text = cell.get_text(strip=True)

    # Extract links
    links = []
    for a in cell.find_all('a'):
        link_url = a.get('href', '')
        # Only add links that aren't empty
        if link_url:
            # Make sure URL is absolute
            link_url = urllib.parse.urljoin(base_url, link_url)

            links.append({"text": a.get_text(strip=True), "url": link_url})

    # Create the sub-item
    sub_item = {"text": right_text, "links": links}

    sub_items.append(sub_item)


def normalize_meeting_details(details):
    """Ensure consistent structure across different meeting formats"""
    # Ensure all standard fields exist
    if "notices" not in details:
        details["notices"] = []

    # Clean up items and ensure consistent structure
    for item in details.get("items", []):
        # Ensure all fields exist
        fields = [
            "time", "location", "type", "section", "secondary_type",
            "sub_items"
        ]
        for field in fields:
            if field not in item:
                item[field] = [] if field == "sub_items" else ""

        # Normalize sub-items
        for sub_item in item.get("sub_items", []):
            if "text" not in sub_item:
                sub_item["text"] = ""
            if "links" not in sub_item:
                sub_item["links"] = []


def extract_commission_number(entity_name):
    """Extract commission number (e.g., 'I', 'II', 'IV') from entity name"""
    match = re.search(r'\b([IVX]+)\b', entity_name)
    if match:
        return match.group(1)
    return ""


def get_commission_id(commission_number, entity_url='', html_content=''):
    """
    Dynamically determine commission ID from various sources

    Args:
        commission_number: Roman numeral or identifier for the commission
        entity_url: Optional URL that might contain the commission ID
        html_content: Optional HTML content that might contain the commission ID

    Returns:
        Commission ID as string or empty string if not found
    """
    # Known mapping for common commissions (for efficiency)
    mapping = {
        'I': '3501',
        'II': '3502',
        'III': '3503',
        'IV': '3504',
        'V': '3505',
        'VI': '3506',
        'VII': '3507',
        'VIII': '3508',
        'IX': '3509',
        'X': '3510',
        'XI': '3511',
        'XII': '3512',
        'XIII': '3513',
        'XIV': '3514'
    }

    # First check our mapping
    if commission_number in mapping:
        return mapping[commission_number]

    # Try to extract from URL if provided
    if entity_url:
        match = re.search(r'shadow_organo_parlamentare=(\d+)', entity_url)
        if match:
            return match.group(1)

    # Try to extract from HTML content if provided
    if html_content:
        # Look for hidden input with commission ID
        match = re.search(r'name="shadow_organo_parlamentare"\s+value="(\d+)"',
                          html_content)
        if match:
            return match.group(1)

        # Look for links that might contain the commission ID
        match = re.search(r'shadow_organo_parlamentare=(\d+)', html_content)
        if match:
            return match.group(1)

    # For unknown commissions, generate a placeholder with the original identifier
    if commission_number:
        return f"unknown_{commission_number}"

    return ""


def format_dates(data):
    """Format all dates in the data to yyyy-mm-dd format"""
    for meeting in data:
        # Format the main date field
        if 'date' in meeting and meeting['date']:
            meeting['date'] = convert_to_iso_date_fixed(meeting['date'])

        # Format the detailed date field if available
        if 'details' in meeting and 'date' in meeting['details'] and meeting[
                'details']['date']:
            meeting['details']['date'] = convert_to_iso_date_fixed(
                meeting['details']['date'])

    return data


def debug_process_table_dates(table, base_url):
    """Debug version of process_table to see what dates are being extracted"""
    print("=== PROCESS TABLE DEBUG ===")

    results = []
    caption = table.find('caption')
    table_title = caption.text.strip() if caption else "Unknown Table"
    print(f"Processing table: {table_title}")

    rows = table.find_all('tr')
    if len(rows) < 3:
        print("Not enough rows in table")
        return results

    # Get days of week from headers
    headers = []
    for th in rows[0].find_all('th')[1:]:
        headers.append(th.text.strip())
    print(f"Headers (days): {headers}")

    # Get dates from second row
    dates = []
    for td in rows[1].find_all('td')[1:]:
        date_text = td.text.strip()
        dates.append(date_text)
        print(f"Raw date from table: '{date_text}'")
    print(f"Raw dates: {dates}")

    # Convert dates to ISO format
    converted_dates = []
    for date_text in dates:
        converted = convert_to_iso_date_fixed(date_text)
        converted_dates.append(converted)
        print(f"'{date_text}' -> '{converted}'")

    print("=== END PROCESS TABLE DEBUG ===")
    return []  # Return empty for debug

def convert_to_iso_date_fixed(date_str, target_week_start=None):
    """
    FIXED: Convert Italian date format to ISO yyyy-mm-dd format
    Uses target week context to avoid wrong month assumptions
    """
    if not date_str or date_str == "NO DATE":
        return ""

    print(f"DEBUG: Converting date_str: '{date_str}'")

    # Get target week if not provided
    if target_week_start is None:
        target_week_start, _ = get_next_monday_friday()

    target_year = target_week_start.year
    target_month = target_week_start.month

    # If it's just a day number (most common case)
    if date_str.isdigit():
        day = int(date_str)

        # FIXED: Use target week's month/year context
        result_date = datetime(target_year, target_month, day).date()

        # Check if this date is within reasonable range of target week
        week_end = target_week_start + timedelta(days=6)

        # If date is way off, try next month
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

        result = result_date.strftime("%Y-%m-%d")
        print(f"DEBUG: Day number conversion: '{date_str}' -> '{result}' (target week: {target_week_start})")
        return result

    # Remove day of week if present
    date_str = re.sub(r'^(lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)\s+', '', date_str, flags=re.IGNORECASE)

    # If it's still just a number after removing day name
    if date_str.isdigit():
        return convert_to_iso_date_fixed(date_str, target_week_start)

    # Italian months mapping
    italian_months = {
        'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4,
        'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
        'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12
    }

    # Try to parse date in format "12 maggio 2025" or "12 maggio"
    for month_name, month_num in italian_months.items():
        # With year
        pattern = rf'(\d+)\s+{month_name}\s+(\d{{4}})'
        match = re.search(pattern, date_str, re.IGNORECASE)
        if match:
            day = match.group(1).zfill(2)
            year = match.group(2)
            result = f"{year}-{month_num:02d}-{day}"
            print(f"DEBUG: Full date conversion: '{date_str}' -> '{result}'")
            return result

        # Without year (use target year)
        pattern = rf'(\d+)\s+{month_name}'
        match = re.search(pattern, date_str, re.IGNORECASE)
        if match:
            day = match.group(1).zfill(2)
            result = f"{target_year}-{month_num:02d}-{day}"
            print(f"DEBUG: Month name conversion: '{date_str}' -> '{result}'")
            return result

    # Try dd/mm/yyyy format
    match = re.search(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})', date_str)
    if match:
        day = match.group(1).zfill(2)
        month = match.group(2).zfill(2)
        year = match.group(3)
        result = f"{year}-{month}-{day}"
        print(f"DEBUG: DD/MM/YYYY conversion: '{date_str}' -> '{result}'")
        return result

    print(f"DEBUG: Could not parse date: '{date_str}'")
    return ""


def save_results(data):
    """Save the scraped data to files"""
    # Create output directory if it doesn't exist
    os.makedirs("output", exist_ok=True)

    # Get current timestamp for filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save to JSON file
    json_file = f"camera_schedule.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Data saved to {json_file}")

    # Generate a summary CSV file for easy viewing
    csv_file = f"camera_schedule_summary.csv"
    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "Type", "Commission", "Commission ID", "Date", "Day", "Time",
            "Meeting Type", "Location", "Section", "Secondary Type",
            "Sub-items"
        ])

        for meeting in data:
            entity_type = "Calendar" if meeting.get(
                'content') == "Calendar entry" else "Commission"
            comm = meeting.get('commission_number', '')
            comm_id = meeting.get('commission_id', '')
            date = meeting.get('date', '')
            day = meeting.get('day', '')

            if entity_type == "Calendar":
                time = meeting.get('time', '')
                writer.writerow([
                    entity_type, "Assemblea Camera", "", date, day, time, "",
                    "", "", "", ""
                ])
            else:
                for item in meeting.get('details', {}).get('items', []):
                    time = item.get('time', '')
                    meeting_type = item.get('type', '')
                    location = item.get('location', '')
                    section = item.get('section', '')
                    secondary_type = item.get('secondary_type', '')
                    sub_items_count = len(item.get('sub_items', []))

                    writer.writerow([
                        entity_type, comm, comm_id, date, day, time,
                        meeting_type, location, section, secondary_type,
                        sub_items_count
                    ])

    print(f"Summary saved to {csv_file}")

    return json_file, csv_file


def process_event_with_openai(event_data):
    """
    Process a single event object with OpenAI API.
    Based on the user's current prompt, this is expected to return a SINGLE flat JSON object.

    Args:
        event_data (dict): A single event/meeting JSON object from the input file.

    Returns:
        dict or None: A single processed and normalized event data as a flat dictionary, 
                      or None if an error occurs or no valid event is extracted.
    """
    try:
        event_data_model = json.dumps(event_data, ensure_ascii=False)
        print(f"Input: Event data Model:\n {event_data_model}\n\n")
        prompt_file_path = 'Prompt/CameraEvents.yaml'
        replacements = {"user_prompt": event_data_model}
        system_prompt, user_prompt, model_params = extract_prompts(
            prompt_file_path, **replacements)
        print("---" * 30)
        print(
            f"CAMERA system_prompt: {system_prompt}, user_prompt: {user_prompt}, model_params: {model_params}"
        )
        print("---" * 30)

        response = client.chat.completions.create(
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
                "agent": "Camera"
            })

        result_text = response.choices[0].message.content.strip()
        result = json.loads(result_text)
        print(
            f"Output: JSON Result:\n {json.dumps(result, indent=2, ensure_ascii=False)}\n\n"
        )

        if isinstance(result, dict) and "events" in result and isinstance(
                result["events"], list):
            return result["events"]
        else:
            print(
                f"Warning: LLM output was valid JSON but missing expected 'events' array: {result_text}"
            )
            return []

    except json.JSONDecodeError as je:
        print(f"Error decoding JSON: {je}. Response was: {result_text}")
        return []
    except Exception as e:
        print(f"Error processing event with OpenAI: {e}")
        return []


def is_value_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


import json


def convert_to_grouped_format(input_file, output_file):
    """
    Convert the existing normalized_events.json to the desired grouped format,
    including new fields like title and details.

    Args:
        input_file (str): Path to the normalized_events.json file
        output_file (str): Path to save the grouped JSON output
    """
    try:
        # Read the input normalized events file
        with open(input_file, 'r', encoding='utf-8') as f:
            input_data = json.load(f)

        # Extract events from the data field
        events = input_data.get('data', [])

        if not events:
            print(f"No events found in {input_file} under the 'data' key.")
            # Create an empty JSON object in the output file or handle as preferred
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            print(f"Empty grouped data written to {output_file}")
            return

        # Initialize the output structure
        grouped_data = {}

        # Process each event and group by entity/source
        for event in events:
            # Get the entity/source as the grouping key.
            # 'source' is the key present in normalized_events.json event objects.
            entity = event.get('source', 'Unknown')

            # Create the entity group if it doesn't exist
            if entity not in grouped_data:
                grouped_data[entity] = []

            # Transform the event object to the new format
            transformed_event = {
                "Source": entity,  # The grouping key itself
                "Date": event.get('date', ''),
                "URL": event.get('url', ''),
                "Title":
                event.get('title',
                          ''),  # Added: New field from normalized_events
                "Details":
                event.get('details',
                          ''),  # Added: New field from normalized_events
                "Description": event.get('description', ''),
                "Summary": event.get('summary', ''),
                "EventType": event.get('event_type', ''),
                "StartTime": event.get('start_time', ''),  # Kept "StartTime"
                "EndTime": event.get('end_time', ''),  # Kept "EndTime"
                "Topic": event.get('topic', '')  # Kept "EndTime"
                # Removed the redundant "Time" field
            }

            # Add the transformed event to its entity group
            grouped_data[entity].append(transformed_event)

        # Write the grouped data to the output file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(grouped_data, f, ensure_ascii=False, indent=2)

        print(f"Successfully converted events data to grouped format.")
        print(f"Output written to {output_file}")

    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.")
    except json.JSONDecodeError:
        print(
            f"Error: Could not decode JSON from '{input_file}'. Ensure it's a valid JSON file."
        )
    except Exception as e:
        print(f"Error converting events data: {e}")


def is_camera_commission(commission_name):
    """Determine if a commission is from Camera based on its name"""
    return (commission_name.startswith("I") or commission_name.startswith("II")
            or commission_name.startswith("III")
            or commission_name.startswith("IV"))


# Add this import at the top of your camera_events.py file
from datetime import datetime, timedelta


# Add the date filtering functions (copy from the utility functions above)
def get_current_week_date_range():
    """Get the date range for the current week (next 7 days from today)."""
    today = datetime.now().date()

    if today.weekday() == 6:  # Sunday
        start_date = today + timedelta(days=1)  # Start from Monday
    elif today.weekday() == 5:  # Saturday
        start_date = today + timedelta(days=2)  # Start from Monday
    else:  # Monday-Friday
        start_date = today

    end_date = start_date + timedelta(days=6)
    return start_date, end_date


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
    """Filter a list of events to only include those in the target week."""
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

    print(f"Filtered {len(filtered_events)} events (skipped {skipped_count} outside target week)")
    return filtered_events


# MODIFICATION 2: Also filter after loading from JSON before Neo4j sync
def load_events_from_json(filename):
    """Load events from a JSON file and filter by current week"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_events = []

        if isinstance(data, dict):
            print(f"Found {len(data)} commissions in JSON file")
            for commission_name, events in data.items():
                print(
                    f"Processing commission: {commission_name} with {len(events)} events"
                )
                all_events.extend(events)
        elif isinstance(data, list):
            print(f"Found {len(data)} events in JSON file (flat list)")
            all_events = data
        else:
            print(f"Unexpected JSON format in {filename}")
            return []

        print(f"Loaded {len(all_events)} total events")

        # ADD THIS: Filter by current week before returning
        filtered_events = filter_events_by_current_week(all_events)
        return filtered_events

    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return []

# ADD this new function that doesn't filter again:
def load_events_from_json_no_filter(filename):
    """Load events from JSON without additional filtering (already filtered)"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_events = []

        if isinstance(data, dict):
            print(f"Found {len(data)} commissions in JSON file")
            for commission_name, events in data.items():
                print(f"Processing commission: {commission_name} with {len(events)} events")
                all_events.extend(events)
        elif isinstance(data, list):
            print(f"Found {len(data)} events in JSON file (flat list)")
            all_events = data
        else:
            print(f"Unexpected JSON format in {filename}")
            return []

        print(f"Loaded {len(all_events)} total events (no additional filtering)")
        return all_events

    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return []


def filter_events_by_current_week_debug(events):
    """Debug version of filter to see what's going wrong"""
    if not events:
        return []

    start_date, end_date = get_next_monday_friday()
    print(f"\n=== FILTER DEBUG ===")
    print(f"Current week range: {start_date} to {end_date}")
    print(f"Total events to filter: {len(events)}")

    filtered_events = []
    skipped_count = 0

    # Check first 10 events in detail
    for i, event in enumerate(events[:10]):
        event_date = event.get('date', '')
        print(f"\nEvent {i+1}:")
        print(f"  Raw date field: '{event_date}'")
        print(f"  Event title: '{event.get('title', 'No title')}'")

        if event_date:
            try:
                parsed_date = datetime.strptime(event_date, "%Y-%m-%d").date()
                in_range = start_date <= parsed_date <= end_date
                print(f"  Parsed date: {parsed_date}")
                print(f"  In range? {in_range}")
                print(f"  Comparison: {start_date} <= {parsed_date} <= {end_date}")

                if in_range:
                    filtered_events.append(event)
                    print(f"  -> INCLUDED")
                else:
                    skipped_count += 1
                    print(f"  -> REJECTED (outside range)")

            except Exception as e:
                print(f"  Parse error: {e}")
                skipped_count += 1
        else:
            print(f"  -> REJECTED (no date)")
            skipped_count += 1

    # Process remaining events normally
    for event in events[10:]:
        event_date = event.get('date', '')
        if is_date_in_current_week(event_date):
            filtered_events.append(event)
        else:
            skipped_count += 1

    print(f"\nFILTER SUMMARY:")
    print(f"  Filtered {len(filtered_events)} events (skipped {skipped_count} outside current week)")
    print(f"=== END FILTER DEBUG ===\n")

    return filtered_events

# Also add this function to check your date range calculation:
def debug_date_range():
    """Debug the date range calculation"""
    today = datetime.now().date()
    start_date, end_date = get_next_monday_friday()

    print(f"\n=== DATE RANGE DEBUG ===")
    print(f"Today: {today}")
    print(f"Today's weekday: {today.weekday()} (0=Monday, 6=Sunday)")
    print(f"Start date: {start_date}")
    print(f"End date: {end_date}")

    # Test some known dates
    test_dates = ['2025-06-16', '2025-06-17', '2025-06-18', '2025-06-19', '2025-06-20', '2025-06-21', '2025-06-22', '2025-06-25', '2025-06-27']

    print(f"\nTesting known dates:")
    for date_str in test_dates:
        try:
            test_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            in_range = start_date <= test_date <= end_date
            print(f"  {date_str} -> {in_range}")
        except Exception as e:
            print(f"  {date_str} -> Error: {e}")

    print(f"=== END DATE RANGE DEBUG ===\n")




def debug_final_event_summary(events):
    """Debug summary of final events before Neo4j"""
    print(f"\n=== FINAL EVENT SUMMARY ===")
    print(f"Total events: {len(events)}")

    # Count by date
    date_counts = {}
    for event in events:
        date = event.get('date', 'NO DATE')
        date_counts[date] = date_counts.get(date, 0) + 1

    print(f"Events by date:")
    for date, count in sorted(date_counts.items()):
        print(f"  {date}: {count} events")

    # Count by source
    source_counts = {}
    for event in events:
        source = event.get('source', 'NO SOURCE')
        source_counts[source] = source_counts.get(source, 0) + 1

    print(f"\nEvents by source (top 10):")
    sorted_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
    for source, count in sorted_sources[:10]:
        print(f"  {source}: {count} events")

    print(f"=== END FINAL EVENT SUMMARY ===\n")
    
def camera_main():
    print("Starting Camera.it schedule scraper...")
    promptDownloader()
    # Use the provided API token for the calendar scraping
    api_token = "2bb56bfb-58ce-4bfe-a945-61123158cde6"
    data = scrape_camera_schedule(api_token=api_token)

    call_webhook_with_success({
        "status": "inprogress",
        "data": {
            "title": f"Extracting the URLs from the camera resource",
            "info": "Processing",
        },
    })

    if data:
        # ADD THIS LINE: Filter events by current week before processing
        # print(f"CAMERA - Before filtering: {len(data)} events")

        # # ADD THIS DEBUG LINE:
        # debug_date_filtering(data)

        # data = filter_events_by_current_week(data)
        # print(f"CAMERA - After filtering: {len(data)} events")

        # # If no events in current week, stop processing
        # if not data:
        #     print("No events found for current week, skipping processing")
        #     return "Camera - No events for current week"

        json_file, csv_file = save_results(data)

        # Print sample of the data
        print("\nSample data:")

        # Show a commission sample first
        commission_sample = next(
            (item
             for item in data if item.get('content') == "Meeting document"),
            None)
        if commission_sample:
            print("\n--- COMMISSION SAMPLE ---")
            print(
                f"Commission: {commission_sample['commission_number']} (ID: {commission_sample['commission_id']})"
            )
            print(
                f"Date: {commission_sample['date']} ({commission_sample['day']})"
            )

            if 'details' in commission_sample and commission_sample['details']:
                details = commission_sample['details']

                if 'title' in details:
                    print(f"Title: {details['title']}")
                if 'date' in details:
                    print(f"Full date: {details['date']}")

                if 'items' in details:
                    print(f"Total agenda items: {len(details['items'])}")

                    if details['items']:
                        for i, sample_item in enumerate(details['items'][:1]):
                            print(f"\nItem {i+1}:")
                            print(f"  Time: {sample_item.get('time', '')}")
                            print(f"  Type: {sample_item.get('type', '')}")
                            print(
                                f"  Section: {sample_item.get('section', '')}")
                            print(
                                f"  Secondary type: {sample_item.get('secondary_type', '')}"
                            )

                            if sample_item.get('sub_items'):
                                print(
                                    f"  Sub-items: {len(sample_item['sub_items'])}"
                                )
                                print(
                                    f"  First sub-item: {sample_item['sub_items'][0]['text'][:50]}..."
                                )

        # Show a calendar sample
        calendar_sample = next(
            (item for item in data if item.get('content') == "Calendar entry"),
            None)
        call_webhook_with_success({
            "status": "inprogress",
            "data": {
                "title": f"Camera extraction continues",
                "info": "Processing",
            },
        })

        if calendar_sample:
            print("\n--- CALENDAR SAMPLE ---")
            print(f"Entity: {calendar_sample['entity']}")
            print(
                f"Date: {calendar_sample['date']} ({calendar_sample['day']})")
            print(f"Time: {calendar_sample.get('time', '')}")
            if 'calendar_info' in calendar_sample:
                print(f"Calendar info: {calendar_sample['calendar_info']}")
            print(f"Row index: {calendar_sample.get('row_index', '')}")
            print(
                f"Content preview: {calendar_sample.get('content_preview', '')}"
            )
            print(
                f"HTML content length: {len(calendar_sample['details'].get('html_content', ''))}"
            )
            print("First 100 chars of HTML content:")
            print(calendar_sample['details'].get('html_content', '')[:100] +
                  "...")
    else:
        print("No data was collected")

    input_file = "camera_schedule.json"
    output_file = "normalized_events.json"
    os.makedirs(
        os.path.dirname(output_file) if os.path.dirname(output_file) else ".",
        exist_ok=True)

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            events_data_list = json.load(f)

        all_normalized_events = []
        total_top_level_entries = len(events_data_list)
        print(
            f"Starting to process {total_top_level_entries} entries from '{input_file}'..."
        )

        for i, event_container in enumerate(events_data_list):
            entity_name = event_container.get('entity', f'Unknown entity (Entry {i+1})')
            print(f"[{i+1}/{total_top_level_entries}] Processing entry for: {entity_name}")
    
            call_webhook_with_success({
                "status": "inprogress",
                "data": {
                    "title": f"Camera extraction is processing for each events",
                    "info": "Processing",
                },
            })
    
            start_time = time.time()
            normalized_events = process_event_with_openai(event_container)
            elapsed = time.time() - start_time
    
            for event in normalized_events:
                call_webhook_with_success({
                    "status": "inprogress",
                    "data": {
                        "title": f"Normalising the camera event ",
                        "info": "Processing",
                    },
                })
                if all([
                    not is_value_empty(event.get("date")),
                    not is_value_empty(event.get("start_time")),
                    not is_value_empty(event.get("event_type")),
                    not (
                        is_value_empty(event.get("title")) and
                        is_value_empty(event.get("summary")) and
                        is_value_empty(event.get("description"))
                    )
                ]):
                    all_normalized_events.append(event)
                    print(f"  ✓ Added event: {event.get('title')} on {event.get('date')} (took {elapsed:.2f}s)")
                else:
                    print(f"  ✗ Skipped empty/incomplete event: {event.get('title')} (took {elapsed:.2f}s)")
    
            time.sleep(0.5)

        # ADD THESE DEBUG CALLS:
        debug_date_range()

        print(f"\nBefore date filtering: {len(all_normalized_events)} processed events")
        filtered_events = filter_events_by_current_week_debug(all_normalized_events)  # Use debug version
        print(f"After date filtering: {len(filtered_events)} events for current week")

        # If no events for current week after processing, stop here
        if not filtered_events:
            print("No events found for current week after processing, skipping Neo4j sync")
            return "Camera - No events for current week"

        # Save the FILTERED events (only current week)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({"data": filtered_events}, f, ensure_ascii=False, indent=2)

        call_webhook_with_success({
            "status": "inprogress",
            "data": {
                "title": f"Filtered events are now stored in json file",
                "info": "Processing",
            },
        })

        print(f"\nProcessing complete. Stored {len(filtered_events)} valid events for current week.")
        print(f"Output written to {output_file}")

    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.")
        return "Camera - File not found error"
    except json.JSONDecodeError:
        print(f"Error: Input file '{input_file}' contains invalid JSON.")
        return "Camera - JSON decode error"
    except Exception as e:
        print(f"Unexpected error in main process: {e}")
        return f"Camera - Processing error: {str(e)}"

    # File paths
    input_file_path = "normalized_events.json"  # Output from your first script
    output_file_path = "grouped_events.json"  # The new desired grouped format

    call_webhook_with_success({
        "status": "inprogress",
        "data": {
            "title": f"Extracted events are now grouped and formatted",
            "info": "Processing",
        },
    })

    # Convert the data
    convert_to_grouped_format(input_file_path, output_file_path)

    # Configuration for Neo4j
    neo4j_uri = "neo4j+s://c94a0c28.databases.neo4j.io"
    neo4j_username = "neo4j"
    neo4j_password = "W0pumaSXNH7U2ZfsNPl4gB1tS4Iw1e-79LbKD7e05fk"
    json_file = "grouped_events.json"  # Your JSON file

    call_webhook_with_success({
        "status": "inprogress",
        "data": {
            "title": f"Working on the Neo4j DB now",
            "info": "Processing",
        },
    })

    # Load Camera events from JSON (these are already filtered for current week)
    print(f"Loading Camera events from {json_file}...")
    events = load_events_from_json_no_filter(json_file)  # Use new function that doesn't filter again

    if not events:
        print("No Camera events found in the JSON file.")
        return "Camera - No events in JSON"

    print(f"Loaded {len(events)} Camera events for Neo4j sync.")

    debug_final_event_summary(events)
    
    # Initialize Neo4j integration
    neo4j = Neo4jIntegration(neo4j_uri, neo4j_username, neo4j_password)

    try:
        # Sync events to Neo4j
        call_webhook_with_success({
            "status": "inprogress",
            "data": {
                "title": f"Syncing events to Neo4j",
                "info": "Processing",
            },
        })

        added_count = neo4j.sync_events_to_neo4j(events)

        print(f"Neo4j sync completed: Added {added_count} events")

    finally:
        # Ensure Neo4j connection is closed properly
        neo4j.close()

    return "Camera Is Done"
