import json
import feedparser
from neo4j import GraphDatabase
from datetime import datetime, timedelta
import os
import requests
import time
from io import StringIO
from urllib.parse import urljoin, urlparse
import re
from openai import OpenAI
from .prompt_extract import extract_prompts
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from queue import Queue

class Neo4jConnection:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._lock = threading.Lock()
    
    def close(self):
        self.driver.close()
    
    def execute_query(self, query, parameters=None):
        with self._lock:
            with self.driver.session() as session:
                result = session.run(query, parameters or {})
                return result.data()

class RSSFeedProcessor:
    def __init__(self, neo4j_url, neo4j_user, neo4j_password, scraper_proxy_url="https://scraper-proxy-usama14.replit.app", scraper_token="7d579b76-a402-4a3a-8837-fada60aa2182", max_feed_workers=5, max_article_workers=3):
        self.neo4j_url = neo4j_url
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.scraper_proxy_url = scraper_proxy_url
        self.scraper_token = scraper_token
        self.max_feed_workers = max_feed_workers
        self.max_article_workers = max_article_workers
        
        # Initialize OpenAI client
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        self.openai_client = OpenAI(api_key=openai_api_key)
        
        # Thread-safe counters
        self._lock = threading.Lock()
        self._total_articles = 0
        self._processed_sources = 0
        self._total_articles_processed = 0
        self._skipped_articles = 0
        self._fact_extracted_articles = 0
        
        # Domain to source name mapping for common news sites
        self.domain_to_source = {
            'techcrunch.com': 'TechCrunch',
            'theverge.com': 'The Verge',
            'wired.com': 'Wired',
            'arstechnica.com': 'Ars Technica',
            'thenextweb.com': 'The Next Web',
            'venturebeat.com': 'VentureBeat',
            'engadget.com': 'Engadget',
            'gizmodo.com': 'Gizmodo',
            'mashable.com': 'Mashable',
            'zdnet.com': 'ZDNet',
            'cnet.com': 'CNET',
            'technologyreview.com': 'MIT Technology Review',
            'ieee.org': 'IEEE Spectrum',
            'reuters.com': 'Reuters',
            'bloomberg.com': 'Bloomberg',
            'wsj.com': 'Wall Street Journal',
            'nytimes.com': 'New York Times',
            'ft.com': 'Financial Times',
            'forbes.com': 'Forbes',
            'businessinsider.com': 'Business Insider',
            'cnbc.com': 'CNBC',
            'theguardian.com': 'The Guardian',
            'bbc.com': 'BBC',
            'bbc.co.uk': 'BBC',
            'washingtonpost.com': 'Washington Post',
            'apnews.com': 'AP News',
            'npr.org': 'NPR',
            'axios.com': 'Axios',
            'politico.com': 'Politico',
            'thehill.com': 'The Hill',
            'vice.com': 'Vice',
            'vox.com': 'Vox',
            'slate.com': 'Slate',
            'salon.com': 'Salon',
            'medium.com': 'Medium',
            'substack.com': 'Substack',
            'github.com': 'GitHub',
            'openai.com': 'OpenAI',
            'anthropic.com': 'Anthropic',
            'deepmind.com': 'DeepMind',
            'microsoft.com': 'Microsoft',
            'google.com': 'Google',
            'apple.com': 'Apple',
            'amazon.com': 'Amazon',
            'facebook.com': 'Facebook',
            'meta.com': 'Meta',
            'twitter.com': 'Twitter',
            'x.com': 'X (Twitter)',
            'linkedin.com': 'LinkedIn',
            'youtube.com': 'YouTube',
            'reddit.com': 'Reddit',
            'hackernews.com': 'Hacker News',
            'ycombinator.com': 'Y Combinator',
            'producthunt.com': 'Product Hunt',
            'indiehackers.com': 'Indie Hackers',
            'dev.to': 'Dev.to',
            'nature.com': 'Nature',
            'science.org': 'Science',
            'scientificamerican.com': 'Scientific American',
            'newscientist.com': 'New Scientist',
            'quantamagazine.org': 'Quanta Magazine',
            'phys.org': 'Phys.org',
            'techxplore.com': 'Tech Xplore',
            'sciencedaily.com': 'Science Daily',
            'eurekalert.org': 'EurekAlert',
            'singularityhub.com': 'Singularity Hub'
        }
    
    def extract_source_from_url(self, url):
        """Extract the source name from a URL"""
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            
            # Remove www. prefix if present
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Check if we have a known mapping
            if domain in self.domain_to_source:
                return self.domain_to_source[domain]
            
            # For unknown domains, create a reasonable source name
            # Remove common TLDs and clean up
            source_name = domain.split('.')[0]
            
            # Capitalize properly
            source_name = source_name.replace('-', ' ').replace('_', ' ')
            source_name = ' '.join(word.capitalize() for word in source_name.split())
            
            print(f"[Thread {threading.current_thread().name}] Extracted source '{source_name}' from URL: {url}")
            return source_name
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error extracting source from URL {url}: {e}")
            return "Unknown Source"
    
    def increment_counters(self, articles_count=0, sources_count=0, articles_processed=0, skipped_articles=0, fact_extracted=0):
        """Thread-safe counter increment"""
        with self._lock:
            self._total_articles += articles_count
            self._processed_sources += sources_count
            self._total_articles_processed += articles_processed
            self._skipped_articles += skipped_articles
            self._fact_extracted_articles += fact_extracted
    
    def get_counters(self):
        """Thread-safe counter getter"""
        with self._lock:
            return self._total_articles, self._processed_sources, self._total_articles_processed, self._skipped_articles, self._fact_extracted_articles
    
    def get_existing_article_urls(self, neo4j_conn, source_name=None):
        """Get all existing article URLs to avoid reprocessing"""
        try:
            if source_name:
                # Get URLs for a specific source
                query = """
                MATCH (s:Source {name: $source_name})-[:PUBLISHED]->(a:Article)
                RETURN a.url as url, a.rss_url as rss_url
                """
                results = neo4j_conn.execute_query(query, {"source_name": source_name})
            else:
                # Get all article URLs
                query = """
                MATCH (a:Article)
                RETURN a.url as url, a.rss_url as rss_url
                """
                results = neo4j_conn.execute_query(query)
            
            existing_urls = set()
            for result in results:
                if result['url']:
                    existing_urls.add(result['url'])
                if result['rss_url']:
                    existing_urls.add(result['rss_url'])
            
            print(f"[Thread {threading.current_thread().name}] Found {len(existing_urls)} existing article URLs")
            return existing_urls
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error getting existing URLs: {e}")
            return set()
    
    def get_environment_mode(self):
        """Get the current environment mode (dev or prod)"""
        return os.environ.get("ENVIRONMENT_MODE", "dev").lower()

    def get_prompt_file_path(self):
        """Get the appropriate prompt file path based on environment mode"""
        mode = self.get_environment_mode()
        
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
        
    def get_source_scoring_prompt_path(self):
        """Get the appropriate source scoring prompt file path based on environment mode"""
        mode = self.get_environment_mode()
        
        if mode == "dev":
            # In dev mode, try /tmp/Prompt first, fallback to Prompt
            tmp_prompt_path = '/tmp/Prompt/source_scoring.yaml'
            if os.path.exists(tmp_prompt_path):
                return tmp_prompt_path
            else:
                return 'Prompt/source_scoring.yaml'
        else:
            # In prod mode, only use Prompt folder
            return 'Prompt/source_scoring.yaml'

    def get_fact_extraction_prompt_path(self):
        """Get the appropriate fact extraction prompt file path based on environment mode"""
        mode = self.get_environment_mode()
        
        if mode == "dev":
            # In dev mode, try /tmp/Prompt first, fallback to Prompt
            tmp_prompt_path = '/tmp/Prompt/fact_extraction.yaml'
            if os.path.exists(tmp_prompt_path):
                return tmp_prompt_path
            else:
                return 'Prompt/fact_extraction.yaml'
        else:
            # In prod mode, only use Prompt folder
            return 'Prompt/fact_extraction.yaml'
        
    def get_source_scoring_prompt_path(self):
        """Get the appropriate source scoring prompt file path based on environment mode"""
        mode = self.get_environment_mode()
        
        if mode == "dev":
            # In dev mode, try /tmp/Prompt first, fallback to Prompt
            tmp_prompt_path = '/tmp/Prompt/source_scoring.yaml'
            if os.path.exists(tmp_prompt_path):
                return tmp_prompt_path
            else:
                return 'Prompt/source_scoring.yaml'
        else:
            # In prod mode, only use Prompt folder
            return 'Prompt/source_scoring.yaml'

    def score_source_relevance(self, source_name):
        """Use LLM to score the relevance of a source"""
        try:
            prompt_file_path = self.get_source_scoring_prompt_path()
            replacements = {"source": source_name}
            system_prompt, user_prompt, model_params = extract_prompts(prompt_file_path, **replacements)
            
            print(f"[Thread {threading.current_thread().name}] Scoring source relevance: {source_name}")
            
            response = self.openai_client.responses.create(
                model=model_params['name'],
                input=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt  
                    },
                ],
                # text={
                #     "format": {
                #     "type": "json_object"
                #     }
                # },
                reasoning={
                    "effort": "medium"
                },
                tools=[
                {
                "type": "web_search_preview",
                "user_location": {
                    "type": "approximate"
                },
                "search_context_size": "medium"
                }
            ]
            )

            # Extract and parse the response
            result = response.output_text
            print(f"score result: {result}")
            score_data = json.loads(result)
            score = score_data.get('score')
            
            print(f"[Thread {threading.current_thread().name}] Source relevance score for {source_name}: {score}")
            return score
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error scoring source relevance: {e}")
            return None

    def update_source_relevancy_score(self, neo4j_conn, source_name, score):
        """Update source node with relevancy score"""
        try:
            query = """
            MATCH (s:Source {name: $source_name})
            SET s.relevancy_score = $score
            RETURN s
            """
            result = neo4j_conn.execute_query(query, {
                "source_name": source_name,
                "score": score
            })
            
            if result:
                print(f"[Thread {threading.current_thread().name}] Updated relevancy score for source {source_name}: {score}")
                return True
            else:
                print(f"[Thread {threading.current_thread().name}] Failed to update relevancy score - source not found: {source_name}")
                return False
                
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error updating source relevancy score: {e}")
            return False

    def get_sources_for_scoring(self, neo4j_conn):
        """Get all sources that don't have a relevancy_score yet"""
        try:
            query = """
            MATCH (c:Category)-[]-(s:Source)
            WHERE s.relevancy_score IS NULL
            RETURN DISTINCT s.name as source_name
            """
            results = neo4j_conn.execute_query(query)
            
            print(f"[Thread {threading.current_thread().name}] Found {len(results)} sources for scoring")
            return results
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error getting sources for scoring: {e}")
            return []

    def process_source_scoring(self, neo4j_conn):
        """Process relevancy scoring for all sources without scores"""
        try:
            print("\n=== Starting source relevancy scoring phase ===")
            
            # Get sources that need scoring
            sources_to_score = self.get_sources_for_scoring(neo4j_conn)
            
            if not sources_to_score:
                print("No sources found for relevancy scoring")
                return 0
            
            print(f"Processing relevancy scoring for {len(sources_to_score)} sources")
            
            scored_count = 0
            for source_data in sources_to_score:
                source_name = source_data['source_name']
                
                # Score the source
                score = self.score_source_relevance(source_name)
                
                if score is not None:
                    # Update the source node with the score
                    success = self.update_source_relevancy_score(neo4j_conn, source_name, score)
                    
                    if success:
                        scored_count += 1
                        print(f"[Thread {threading.current_thread().name}] Successfully scored source: {source_name} (score: {score})")
                    else:
                        print(f"[Thread {threading.current_thread().name}] Failed to update score for source: {source_name}")
                else:
                    print(f"[Thread {threading.current_thread().name}] Failed to generate score for source: {source_name}")
                
                # Brief delay between API calls to avoid rate limiting
                time.sleep(0.5)
            
            print(f"=== Completed source scoring: {scored_count} sources scored ===\n")
            return scored_count
            
        except Exception as e:
            print(f"Error in source scoring process: {e}")
            return 0

    def filter_article_relevance(self, article_title, article_content):
        """Use LLM to determine if article is relevant to AI"""
        try:
            # Combine title and content for analysis
            article_text = f"Title: {article_title}\n\nContent: {article_content}"
            
            prompt_file_path = self.get_prompt_file_path()
            replacements = {"articles": article_text}
            system_prompt, user_prompt, model_params = extract_prompts(prompt_file_path, **replacements)
            
            print(f"[Thread {threading.current_thread().name}] Filtering article relevance: {article_title[:100]}...")
            
            response = self.openai_client.chat.completions.create(
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
                response_format={"type": "json_object"},
                reasoning_effort="medium"
            )

            # Extract and parse the response
            result = response.choices[0].message.content.strip()
            relevance_data = json.loads(result)
            is_relevant = relevance_data.get('isRelevant', False)
            
            print(f"[Thread {threading.current_thread().name}] Article relevance result: {is_relevant}")
            return is_relevant
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error filtering article relevance: {e}")
            # Default to True to avoid losing potentially relevant articles
            return True

    def extract_facts_from_article(self, article_title, article_content):
        """Use LLM to extract facts from article content"""
        try:
            # Combine title and content for analysis
            article_text = f"Title: {article_title}\n\nContent: {article_content}"
            
            prompt_file_path = self.get_fact_extraction_prompt_path()
            replacements = {"articles": article_text}
            system_prompt, user_prompt, model_params = extract_prompts(prompt_file_path, **replacements)
            
            print(f"[Thread {threading.current_thread().name}] Extracting facts from article: {article_title[:100]}...")
            
            response = self.openai_client.chat.completions.create(
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
                response_format={"type": "json_object"},
                reasoning_effort="medium"
            )

            # Extract and parse the response
            result = response.choices[0].message.content.strip()
            fact_data = json.loads(result)
            
            print(f"[Thread {threading.current_thread().name}] Successfully extracted facts from article")
            return fact_data
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error extracting facts from article: {e}")
            return None

    def get_articles_for_fact_extraction(self, neo4j_conn):
        """Get all articles where isRelevant=true and fact_summary is null"""
        try:
            query = """
            MATCH (c:Category)-[]-(s:Source)-[:PUBLISHED]->(a:Article)
            WHERE a.isRelevant = true AND a.fact_summary IS NULL
            RETURN a.title as title, a.content as content, a.url as url, 
                   a.rss_url as rss_url, s.name as source_name
            """
            results = neo4j_conn.execute_query(query)
            
            print(f"[Thread {threading.current_thread().name}] Found {len(results)} articles for fact extraction")
            return results
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error getting articles for fact extraction: {e}")
            return []

    def update_article_fact_summary(self, neo4j_conn, article_url, rss_url, fact_summary):
        """Update article node with fact summary"""
        try:
            # Convert fact_summary dict to JSON string for storage
            fact_summary_json = json.dumps(fact_summary)
            
            query = """
            MATCH (a:Article)
            WHERE a.url = $url OR a.rss_url = $rss_url
            SET a.fact_summary = $fact_summary
            RETURN a
            """
            result = neo4j_conn.execute_query(query, {
                "url": article_url,
                "rss_url": rss_url,
                "fact_summary": fact_summary_json
            })
            
            if result:
                print(f"[Thread {threading.current_thread().name}] Updated fact summary for article: {article_url[:100]}...")
                return True
            else:
                print(f"[Thread {threading.current_thread().name}] Failed to update fact summary - article not found: {article_url[:100]}...")
                return False
                
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error updating article fact summary: {e}")
            return False

    def process_single_article_fact_extraction(self, article_data, neo4j_conn):
        """Process fact extraction for a single article - designed for multithreading"""
        try:
            title = article_data['title']
            content = article_data['content']
            url = article_data['url']
            rss_url = article_data['rss_url']
            
            # Extract facts from the article
            fact_summary = self.extract_facts_from_article(title, content)
            
            if fact_summary:
                # Update the article node with fact summary
                success = self.update_article_fact_summary(neo4j_conn, url, rss_url, fact_summary)
                
                if success:
                    self.increment_counters(fact_extracted=1)
                    return True
                else:
                    print(f"[Thread {threading.current_thread().name}] Failed to update fact summary for: {title[:100]}...")
                    return False
            else:
                print(f"[Thread {threading.current_thread().name}] No facts extracted for: {title[:100]}...")
                return False
                
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error in fact extraction process: {e}")
            return False

    def process_fact_extraction_for_relevant_articles(self, neo4j_conn):
        """Process fact extraction for all relevant articles without fact_summary"""
        try:
            print("Starting fact extraction for relevant articles...")
            
            # Get articles that need fact extraction
            articles_to_process = self.get_articles_for_fact_extraction(neo4j_conn)
            
            if not articles_to_process:
                print("No articles found for fact extraction")
                return 0
            
            print(f"Processing fact extraction for {len(articles_to_process)} articles")
            
            # Process articles concurrently using ThreadPoolExecutor
            processed_count = 0
            with ThreadPoolExecutor(max_workers=self.max_article_workers) as executor:
                # Submit all fact extraction tasks
                future_to_article = {
                    executor.submit(self.process_single_article_fact_extraction, article, neo4j_conn): article 
                    for article in articles_to_process
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_article):
                    article = future_to_article[future]
                    try:
                        success = future.result()
                        if success:
                            processed_count += 1
                            print(f"[Thread {threading.current_thread().name}] Fact extraction completed for: {article['title'][:50]}...")
                    except Exception as e:
                        print(f"[Thread {threading.current_thread().name}] Exception during fact extraction for '{article['title'][:50]}...': {e}")
                
                # Add small delay between batches to avoid overwhelming the API
                time.sleep(0.5)
            
            print(f"Successfully extracted facts from {processed_count} articles")
            return processed_count
            
        except Exception as e:
            print(f"Error in fact extraction process: {e}")
            return 0

    def load_rss_feeds(self, config_file='rss_feeds.json'):
        """Load RSS feeds configuration from rss_feeds.json"""
        try:
            # Get the directory where this file is located
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, config_file)
            
            print(f"Loading RSS feeds config from: {config_path}")
            
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"{config_file} file not found at {config_path}")
            return {"feeds": []}
        except json.JSONDecodeError:
            print(f"Error parsing {config_file}")
            return {"feeds": []}
    
    def is_techmeme_source(self, source_name, article_url):
        """Check if this is a Techmeme source"""
        return (
            source_name.lower() == "techmeme" or 
            "techmeme.com" in article_url.lower()
        )
    
    def is_tldr_source(self, source_name):
        """Check if this is a TLDR source"""
        return source_name.lower() == "tldr" or "tldr ai" in source_name.lower()
    
    def extract_tldr_articles_from_page(self, tldr_html):
        """Extract individual articles from TLDR newsletter page"""
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(tldr_html, 'html.parser')
            articles = []
            
            # Find all article sections
            article_sections = soup.find_all('article', class_='mt-3')
            
            print(f"[Thread {threading.current_thread().name}] Found {len(article_sections)} article sections in TLDR page")
            
            for article_section in article_sections:
                try:
                    # Find the main link and title
                    main_link = article_section.find('a', class_='font-bold')
                    if not main_link:
                        continue
                    
                    article_url = main_link.get('href')
                    if not article_url:
                        continue
                    
                    # Get the title from h3
                    title_element = main_link.find('h3')
                    if not title_element:
                        continue
                    
                    article_title = title_element.get_text(strip=True)
                    
                    # Get the summary from newsletter-html div
                    summary_div = article_section.find('div', class_='newsletter-html')
                    summary = summary_div.get_text(strip=True) if summary_div else ""
                    
                    # Skip sponsored content
                    if "(Sponsor)" in article_title or "utm_source=sponsored" in article_url:
                        print(f"[Thread {threading.current_thread().name}] Skipping sponsored content: {article_title[:50]}...")
                        continue
                    
                    articles.append({
                        'title': article_title,
                        'url': article_url,
                        'tldr_summary': summary
                    })
                    
                    print(f"[Thread {threading.current_thread().name}] Extracted TLDR article: {article_title[:50]}...")
                    
                except Exception as e:
                    print(f"[Thread {threading.current_thread().name}] Error extracting individual TLDR article: {e}")
                    continue
            
            print(f"[Thread {threading.current_thread().name}] Successfully extracted {len(articles)} articles from TLDR page")
            return articles
            
        except ImportError:
            print("BeautifulSoup not available for TLDR article extraction")
            return []
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error extracting TLDR articles: {e}")
            return []
    
    def extract_actual_article_url_from_techmeme(self, techmeme_html):
        """Extract the actual source article URL from Techmeme page HTML"""
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(techmeme_html, 'html.parser')
            
            # Techmeme typically has the main article link in several possible locations
            # Try different selectors to find the main article link
            
            # Method 1: Look for the main story link (usually the first/largest link)
            main_story_selectors = [
                '.ii a[href]:first-child',  # Main story link
                '.item .ii a[href]',        # Item story link
                'a.ii',                     # Direct story link
                '.storylink',               # Story link class
                'a[href*="http"]:not([href*="techmeme.com"])'  # External links only
            ]
            
            for selector in main_story_selectors:
                links = soup.select(selector)
                if links:
                    href = links[0].get('href')
                    if href and not 'techmeme.com' in href:
                        print(f"[Thread {threading.current_thread().name}] Found actual article URL via selector '{selector}': {href}")
                        return href
            
            # Method 2: Look for external links that aren't Techmeme
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href')
                if (href and 
                    href.startswith('http') and 
                    'techmeme.com' not in href and
                    not href.startswith('mailto:') and
                    not href.startswith('javascript:')):
                    print(f"[Thread {threading.current_thread().name}] Found external article URL: {href}")
                    return href
            
            print(f"[Thread {threading.current_thread().name}] Could not extract actual article URL from Techmeme page")
            return None
            
        except ImportError:
            print("BeautifulSoup not available for Techmeme URL extraction")
            return None
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error extracting article URL from Techmeme: {e}")
            return None
    
    def fetch_content_via_proxy(self, url, max_retries=3):
        """Fetch content using the scraper proxy service"""
        headers = {
            'Authorization': f'Bearer {self.scraper_token}',
            'Content-Type': 'application/json'
        }
        
        # Prepare the request data - enable JavaScript rendering
        request_data = {
            "url": url,
            "render": True  # Enable JavaScript rendering
        }
        
        for attempt in range(max_retries):
            try:
                print(f"[Thread {threading.current_thread().name}] Fetching content via proxy (attempt {attempt + 1}): {url}")
                
                # Use POST request with JSON data
                response = requests.post(
                    f"{self.scraper_proxy_url}/api/scrape",
                    headers=headers,
                    json=request_data,
                    timeout=60  # Longer timeout for content scraping
                )
                
                print(f"[Thread {threading.current_thread().name}] Proxy response status: {response.status_code}")
                
                if response.status_code == 202:
                    # Request queued, wait and retry
                    print(f"[Thread {threading.current_thread().name}] Request queued, waiting 10 seconds before retry...")
                    time.sleep(10)
                    continue
                
                if response.status_code == 200:
                    # Check if response is JSON or plain text
                    content_type = response.headers.get('content-type', '').lower()
                    
                    if 'application/json' in content_type:
                        json_response = response.json()
                        content = json_response.get('html', json_response.get('text', ''))
                        print(f"[Thread {threading.current_thread().name}] Successfully fetched content via proxy ({len(content)} characters)")
                        return content
                    else:
                        print(f"[Thread {threading.current_thread().name}] Successfully fetched content via proxy ({len(response.text)} characters)")
                        return response.text
                
                else:
                    print(f"[Thread {threading.current_thread().name}] Scraper proxy returned status {response.status_code}: {response.text}")
                    
            except requests.exceptions.RequestException as e:
                print(f"[Thread {threading.current_thread().name}] Request error on attempt {attempt + 1} for {url}: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 2  # Exponential backoff
                    print(f"[Thread {threading.current_thread().name}] Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    continue
            except Exception as e:
                print(f"[Thread {threading.current_thread().name}] Unexpected error on attempt {attempt + 1} for {url}: {e}")
        
        print(f"[Thread {threading.current_thread().name}] Failed to fetch content via proxy after {max_retries} attempts: {url}")
        return None
    
    def fetch_content_directly(self, url, max_retries=3):
        """Fetch content directly using requests as fallback"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        for attempt in range(max_retries):
            try:
                print(f"[Thread {threading.current_thread().name}] Fetching content directly (attempt {attempt + 1}): {url}")
                
                response = requests.get(url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    print(f"[Thread {threading.current_thread().name}] Successfully fetched content directly ({len(response.text)} characters)")
                    return response.text
                else:
                    print(f"[Thread {threading.current_thread().name}] Failed to fetch content directly, status code: {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                print(f"[Thread {threading.current_thread().name}] Request error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1  # Exponential backoff
                    print(f"[Thread {threading.current_thread().name}] Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    continue
            except Exception as e:
                print(f"[Thread {threading.current_thread().name}] Unexpected error on attempt {attempt + 1}: {e}")
        
        print(f"[Thread {threading.current_thread().name}] Failed to fetch content directly after {max_retries} attempts: {url}")
        return None
    
    def fetch_rss_feed_directly(self, feed_url, max_retries=3):
        """Fetch RSS feed directly without proxy"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        for attempt in range(max_retries):
            try:
                print(f"[Thread {threading.current_thread().name}] Fetching RSS feed directly (attempt {attempt + 1}): {feed_url}")
                
                response = requests.get(feed_url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    print(f"[Thread {threading.current_thread().name}] Successfully fetched RSS feed ({len(response.text)} characters)")
                    return response.text
                else:
                    print(f"[Thread {threading.current_thread().name}] Failed to fetch RSS feed, status code: {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                print(f"[Thread {threading.current_thread().name}] Request error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1  # Exponential backoff
                    print(f"[Thread {threading.current_thread().name}] Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    continue
            except Exception as e:
                print(f"[Thread {threading.current_thread().name}] Unexpected error on attempt {attempt + 1}: {e}")
        
        print(f"[Thread {threading.current_thread().name}] Failed to fetch RSS feed after {max_retries} attempts: {feed_url}")
        return None
    
    def clean_html_content(self, html_content):
        """Clean HTML content by removing scripts, styles, and unnecessary elements while preserving structure"""
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove unwanted elements
            unwanted_elements = [
                'script',           # JavaScript
                'style',            # CSS styles
                'link[rel="stylesheet"]',  # CSS links
                'meta',             # Meta tags
                'noscript',         # NoScript content
                'iframe',           # Embedded frames
                'object',           # Embedded objects
                'embed',            # Embedded content
                'form',             # Forms
                'input',            # Input fields
                'button',           # Buttons
                'nav',              # Navigation (usually not article content)
                'header',           # Page headers
                'footer',           # Page footers
                'aside',            # Sidebars
                '.advertisement',   # Common ad classes
                '.ads',
                '.sidebar',
                '.menu',
                '.navigation',
                '.footer',
                '.header',
                '.comments',
                '#comments',
                '.social-share',
                '.social-sharing'
            ]
            
            for selector in unwanted_elements:
                for element in soup.select(selector):
                    element.decompose()
            
            # Find main content areas (prefer article content)
            content_selectors = [
                'article', 
                '[role="main"]', 
                '.content', 
                '.article-content', 
                '.post-content',
                '.entry-content',
                'main',
                '.article-body',
                '.story-body',
                '.post-body'
            ]
            
            main_content = None
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    main_content = elements[0]
                    break
            
            # If no main content found, use body or entire document
            if not main_content:
                main_content = soup.body if soup.body else soup
            
            # Remove all style attributes from remaining elements
            for element in main_content.find_all():
                if element.has_attr('style'):
                    del element['style']
                if element.has_attr('class'):
                    # Keep classes but remove common problematic ones
                    classes = element['class']
                    cleaned_classes = [c for c in classes if not any(bad in c.lower() for bad in ['ad', 'social', 'share', 'comment'])]
                    if cleaned_classes:
                        element['class'] = cleaned_classes
                    else:
                        del element['class']
            
            # Get the cleaned HTML
            cleaned_html = str(main_content)
            
            # Additional text-based cleaning
            cleaned_html = re.sub(r'<!--.*?-->', '', cleaned_html, flags=re.DOTALL)  # Remove HTML comments
            cleaned_html = re.sub(r'\s+', ' ', cleaned_html)  # Normalize whitespace
            cleaned_html = cleaned_html.strip()
            
            print(f"[Thread {threading.current_thread().name}] Cleaned HTML: {len(html_content)} chars -> {len(cleaned_html)} chars")
            return cleaned_html
            
        except ImportError:
            print("BeautifulSoup not available, performing basic cleanup")
            # Basic cleanup without BeautifulSoup
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<!--.*?-->', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'\s+', ' ', html_content)
            return html_content.strip()
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error cleaning HTML content: {e}")
            # Return original content with basic cleanup
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            return html_content
    
    def fetch_article_content(self, aggregator_name, article_url, article_title):
        """Fetch full article content with fallback to direct requests, handling Techmeme special case"""
        print(f"[Thread {threading.current_thread().name}] Fetching content for: {article_title}")
        
        if self.is_techmeme_source(aggregator_name, article_url):
            print(f"[Thread {threading.current_thread().name}] Detected Techmeme source - using two-step process")
            
            # Step 1: Fetch the Techmeme page (try proxy first, then direct)
            techmeme_html = self.fetch_content_via_proxy(article_url)
            
            if not techmeme_html:
                print(f"[Thread {threading.current_thread().name}] Proxy failed for Techmeme page, trying direct request...")
                techmeme_html = self.fetch_content_directly(article_url)
            
            if not techmeme_html:
                print(f"[Thread {threading.current_thread().name}] Failed to fetch Techmeme page via both proxy and direct request")
                return None, article_url
            
            # Step 2: Extract the actual article URL from Techmeme page
            actual_article_url = self.extract_actual_article_url_from_techmeme(techmeme_html)
            
            if not actual_article_url:
                print(f"[Thread {threading.current_thread().name}] Could not extract actual article URL from Techmeme page")
                return None, article_url
            
            print(f"[Thread {threading.current_thread().name}] Extracted actual article URL: {actual_article_url}")
            
            # Step 3: Fetch the actual article content (try proxy first, then direct)
            time.sleep(1)  # Brief pause between requests
            actual_content = self.fetch_content_via_proxy(actual_article_url)
            
            if not actual_content:
                print(f"[Thread {threading.current_thread().name}] Proxy failed for actual article, trying direct request...")
                actual_content = self.fetch_content_directly(actual_article_url)
            
            if actual_content:
                cleaned_html = self.clean_html_content(actual_content)
                print(f"[Thread {threading.current_thread().name}] Successfully fetched Techmeme article content ({len(cleaned_html)} chars)")
                return cleaned_html, actual_article_url
            else:
                print(f"[Thread {threading.current_thread().name}] Failed to fetch actual article from extracted URL via both proxy and direct request")
                return None, actual_article_url
        
        else:
            # Regular article - try proxy first, then direct requests
            content = self.fetch_content_via_proxy(article_url)
            
            if not content:
                print(f"[Thread {threading.current_thread().name}] Proxy failed for regular article, trying direct request...")
                content = self.fetch_content_directly(article_url)
            
            if content:
                cleaned_html = self.clean_html_content(content)
                print(f"[Thread {threading.current_thread().name}] Successfully fetched article content ({len(cleaned_html)} chars)")
                return cleaned_html, article_url
            else:
                print(f"[Thread {threading.current_thread().name}] Failed to fetch article content via both proxy and direct request")
                return None, article_url
    
    def process_single_tldr_article(self, aggregator_name, article_info, cutoff_date, existing_urls):
        """Process a single TLDR article - designed for multithreading"""
        try:
            article_url = article_info['url']
            article_title = article_info['title']
            tldr_summary = article_info['tldr_summary']
            
            # EARLY CHECK: Skip if this article URL already exists in database
            if article_url in existing_urls:
                print(f"[Thread {threading.current_thread().name}] Skipping TLDR article - already exists in database: {article_title[:100]}...")
                self.increment_counters(skipped_articles=1)
                return None
            
            print(f"[Thread {threading.current_thread().name}] Processing new TLDR article: {article_title[:100]}...")
            
            # Extract the actual source from the article URL
            actual_source_name = self.extract_source_from_url(article_url)
            
            # Fetch full article content
            full_content = tldr_summary  # Fallback to TLDR summary
            final_url = article_url
            
            article_content, final_article_url = self.fetch_article_content(
                aggregator_name, article_url, article_title
            )
            
            # ADDITIONAL CHECK: After getting final URL, check if it exists
            if final_article_url and final_article_url != article_url and final_article_url in existing_urls:
                print(f"[Thread {threading.current_thread().name}] Skipping TLDR article - final URL already exists in database: {final_article_url}")
                self.increment_counters(skipped_articles=1)
                return None
            
            if article_content and len(article_content.strip()) > len(tldr_summary.strip()):
                full_content = article_content
                final_url = final_article_url
                print(f"[Thread {threading.current_thread().name}] Used full article HTML content ({len(full_content)} chars)")
            else:
                print(f"[Thread {threading.current_thread().name}] Using TLDR summary ({len(tldr_summary)} chars)")
            
            # CHECK CONTENT LENGTH: Skip if content is too short
            if len(full_content.strip()) < 200:
                print(f"[Thread {threading.current_thread().name}] Skipping TLDR article - content too short ({len(full_content.strip())} chars < 200): {article_title[:100]}...")
                self.increment_counters(skipped_articles=1)
                return None
            
            # Brief delay to avoid overwhelming the services
            time.sleep(0.5)
            
            # Filter article for AI relevance using LLM
            print(f"[Thread {threading.current_thread().name}] Filtering TLDR article for AI relevance: {article_title}")
            is_relevant = self.filter_article_relevance(article_title, full_content)
            
            # Brief delay after LLM call
            time.sleep(0.3)
            
            article_data = {
                'title': article_title,
                'content': full_content,  # Full article content
                'tldr_summary': tldr_summary,  # TLDR summary
                'date': datetime.now(),  # Store as datetime object
                'url': final_url,  # Use the final article URL
                'rss_url': article_url,  # Keep original TLDR URL
                'published_date': datetime.now(),
                'isRelevant': is_relevant,
                'retrieved_via': 'TLDR',  # Mark as retrieved via TLDR
                'actual_source': actual_source_name  # The actual news source
            }
            
            print(f"[Thread {threading.current_thread().name}] Successfully processed TLDR article: {article_title[:100]}...")
            self.increment_counters(articles_processed=1)
            return article_data
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error processing TLDR article: {e}")
            return None
    
    def process_single_article(self, aggregator_name, entry, cutoff_date, existing_urls):
        """Process a single article - designed for multithreading"""
        try:
            # Parse the published date
            pub_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                pub_date = datetime(*entry.updated_parsed[:6])
            
            # If no date found, skip this entry
            if not pub_date:
                print(f"[Thread {threading.current_thread().name}] Skipping article - no date found")
                return None
            
            # Only include articles from the last N days
            if pub_date < cutoff_date:
                print(f"[Thread {threading.current_thread().name}] Skipping article - too old ({pub_date})")
                return None
            
            # Get basic article info from RSS
            article_url = entry.link if hasattr(entry, 'link') else ''
            article_title = entry.title if hasattr(entry, 'title') else ''
            
            # EARLY CHECK: Skip if this article URL already exists in database
            if article_url in existing_urls:
                print(f"[Thread {threading.current_thread().name}] Skipping article - already exists in database: {article_title[:100]}...")
                self.increment_counters(skipped_articles=1)
                return None
            
            print(f"[Thread {threading.current_thread().name}] Processing new article: {article_title[:100]}...")
            
            # Get RSS content
            rss_content = ""
            if hasattr(entry, 'content') and entry.content:
                rss_content = entry.content[0].value
            elif hasattr(entry, 'summary'):
                rss_content = entry.summary
            elif hasattr(entry, 'description'):
                rss_content = entry.description
            
            # Fetch full article content with fallback to direct requests
            full_content = rss_content  # Fallback to RSS content
            final_url = article_url  # May change for Techmeme
            actual_source_name = self.extract_source_from_url(article_url)  # Default source
            
            if article_url:
                article_content, final_article_url = self.fetch_article_content(
                    aggregator_name, article_url, article_title
                )
                
                # ADDITIONAL CHECK: After getting final URL (especially for Techmeme), check if it exists
                if final_article_url and final_article_url != article_url and final_article_url in existing_urls:
                    print(f"[Thread {threading.current_thread().name}] Skipping article - final URL already exists in database: {final_article_url}")
                    self.increment_counters(skipped_articles=1)
                    return None
                
                if article_content and len(article_content.strip()) > len(rss_content.strip()):
                    full_content = article_content
                    final_url = final_article_url
                    # Update actual source from final URL (important for Techmeme)
                    actual_source_name = self.extract_source_from_url(final_url)
                    print(f"[Thread {threading.current_thread().name}] Used full article HTML content ({len(full_content)} chars)")
                else:
                    print(f"[Thread {threading.current_thread().name}] Using RSS content ({len(rss_content)} chars)")
                
                # Brief delay to avoid overwhelming the services
                time.sleep(0.5)
            
            # CHECK CONTENT LENGTH: Skip if content is too short
            if len(full_content.strip()) < 200:
                print(f"[Thread {threading.current_thread().name}] Skipping article - content too short ({len(full_content.strip())} chars < 200): {article_title[:100]}...")
                self.increment_counters(skipped_articles=1)
                return None
            
            # Filter article for AI relevance using LLM
            print(f"[Thread {threading.current_thread().name}] Filtering article for AI relevance: {article_title}")
            is_relevant = self.filter_article_relevance(article_title, full_content)
            
            # Brief delay after LLM call
            time.sleep(0.3)
            
            # Determine if this was retrieved via an aggregator
            retrieved_via = None
            if self.is_techmeme_source(aggregator_name, article_url):
                retrieved_via = 'Techmeme'
            elif self.is_tldr_source(aggregator_name):
                retrieved_via = 'TLDR'
            
            article_data = {
                'title': article_title,
                'content': full_content,  # Now contains cleaned HTML
                'rss_content': rss_content,  # Keep original RSS content as backup
                'date': pub_date,  # Store as datetime object
                'url': final_url,  # Use the final article URL (actual source for Techmeme)
                'rss_url': article_url,  # Keep original RSS URL
                'published_date': pub_date,
                'isRelevant': is_relevant,  # Add relevance filtering result
                'retrieved_via': retrieved_via,  # Mark if retrieved via aggregator
                'actual_source': actual_source_name  # The actual news source
            }
            
            print(f"[Thread {threading.current_thread().name}] Successfully processed article: {article_title[:100]}...")
            self.increment_counters(articles_processed=1)
            return article_data
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error processing article: {e}")
            return None
    
    def parse_tldr_feed(self, aggregator_name, feed_url, days_back=1, existing_urls=None):
        """Parse TLDR RSS feed and extract individual articles from each newsletter"""
        try:
            print(f"[Thread {threading.current_thread().name}] Parsing TLDR RSS feed: {feed_url}")
            
            # Use existing URLs if provided, otherwise get from database
            if existing_urls is None:
                existing_urls = set()
            
            # Fetch RSS content directly
            rss_content = self.fetch_rss_feed_directly(feed_url)
            
            if not rss_content:
                print(f"[Thread {threading.current_thread().name}] Failed to fetch TLDR RSS content for {feed_url}")
                return []
            
            # Parse the RSS content using feedparser
            feed = feedparser.parse(rss_content)
            
            if not feed.entries:
                print(f"[Thread {threading.current_thread().name}] No entries found in TLDR RSS feed: {feed_url}")
                return []
            
            cutoff_date = datetime.now() - timedelta(days=days_back)
            all_articles = []
            
            # Process each TLDR newsletter entry
            for entry in feed.entries:
                try:
                    # Parse the published date
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_date = datetime(*entry.updated_parsed[:6])
                    
                    if not pub_date or pub_date < cutoff_date:
                        continue
                    
                    # Get the TLDR newsletter URL
                    newsletter_url = entry.link if hasattr(entry, 'link') else ''
                    if not newsletter_url:
                        continue
                    
                    print(f"[Thread {threading.current_thread().name}] Fetching TLDR newsletter page: {newsletter_url}")
                    
                    # Fetch the TLDR newsletter page
                    newsletter_html = self.fetch_content_via_proxy(newsletter_url)
                    
                    if not newsletter_html:
                        print(f"[Thread {threading.current_thread().name}] Proxy failed for TLDR page, trying direct request...")
                        newsletter_html = self.fetch_content_directly(newsletter_url)
                    
                    if not newsletter_html:
                        print(f"[Thread {threading.current_thread().name}] Failed to fetch TLDR newsletter page")
                        continue
                    
                    # Extract individual articles from the newsletter page
                    articles = self.extract_tldr_articles_from_page(newsletter_html)
                    
                    if articles:
                        print(f"[Thread {threading.current_thread().name}] Found {len(articles)} articles in TLDR newsletter from {pub_date}")
                        all_articles.extend(articles)
                    
                    # Brief delay between newsletter pages
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"[Thread {threading.current_thread().name}] Error processing TLDR newsletter entry: {e}")
                    continue
            
            print(f"[Thread {threading.current_thread().name}] Total TLDR articles to process: {len(all_articles)}")
            
            if not all_articles:
                return []
            
            # Process articles concurrently using ThreadPoolExecutor
            processed_articles = []
            with ThreadPoolExecutor(max_workers=self.max_article_workers) as executor:
                # Submit all article processing tasks
                future_to_article = {
                    executor.submit(self.process_single_tldr_article, aggregator_name, article_info, cutoff_date, existing_urls): article_info 
                    for article_info in all_articles
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_article):
                    article_info = future_to_article[future]
                    try:
                        article_data = future.result()
                        if article_data:  # Only add successful results
                            processed_articles.append(article_data)
                            print(f"[Thread {threading.current_thread().name}] TLDR article completed: {article_data['title'][:50]}...")
                    except Exception as e:
                        article_title = article_info.get('title', 'Unknown')
                        print(f"[Thread {threading.current_thread().name}] Exception processing TLDR article '{article_title}': {e}")
            
            print(f"[Thread {threading.current_thread().name}] Successfully processed {len(processed_articles)} new TLDR articles")
            return processed_articles
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error parsing TLDR RSS feed {feed_url}: {e}")
            return []
    
    def parse_rss_feed(self, aggregator_name, feed_url, days_back=1, existing_urls=None):
        """Parse RSS feed and return articles from the last N days, processing articles concurrently"""
        # Check if this is a TLDR source
        if self.is_tldr_source(aggregator_name):
            return self.parse_tldr_feed(aggregator_name, feed_url, days_back, existing_urls)
        
        try:
            print(f"[Thread {threading.current_thread().name}] Parsing RSS feed: {feed_url}")
            
            # Use existing URLs if provided, otherwise get from database
            if existing_urls is None:
                existing_urls = set()
            
            # Fetch RSS content directly
            rss_content = self.fetch_rss_feed_directly(feed_url)
            
            if not rss_content:
                print(f"[Thread {threading.current_thread().name}] Failed to fetch RSS content for {feed_url}")
                return []
            
            # Parse the RSS content using feedparser
            feed = feedparser.parse(rss_content)
            
            if not feed.entries:
                print(f"[Thread {threading.current_thread().name}] No entries found in RSS feed: {feed_url}")
                return []
            
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            # Filter entries by date first to avoid processing old articles
            recent_entries = []
            for entry in feed.entries:
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6])
                
                if pub_date and pub_date >= cutoff_date:
                    recent_entries.append(entry)
            
            print(f"[Thread {threading.current_thread().name}] Found {len(recent_entries)} recent entries to process from {feed_url}")
            
            if not recent_entries:
                return []
            
            # Process articles concurrently using ThreadPoolExecutor
            articles = []
            with ThreadPoolExecutor(max_workers=self.max_article_workers) as executor:
                # Submit all article processing tasks
                future_to_entry = {
                    executor.submit(self.process_single_article, aggregator_name, entry, cutoff_date, existing_urls): entry 
                    for entry in recent_entries
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_entry):
                    entry = future_to_entry[future]
                    try:
                        article_data = future.result()
                        if article_data:  # Only add successful results
                            articles.append(article_data)
                            print(f"[Thread {threading.current_thread().name}] Article completed: {article_data['title'][:50]}...")
                    except Exception as e:
                        entry_title = getattr(entry, 'title', 'Unknown')
                        print(f"[Thread {threading.current_thread().name}] Exception processing article '{entry_title}': {e}")
            
            print(f"[Thread {threading.current_thread().name}] Successfully processed {len(articles)} new articles from {feed_url}")
            return articles
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error parsing RSS feed {feed_url}: {e}")
            return []
    
    def create_neo4j_nodes_and_relationships(self, neo4j_conn, category_name, aggregator_name, aggregator_url, articles):
        """Create nodes and relationships in Neo4j with actual sources"""
        try:
            # Create Category node
            category_query = """
            MERGE (c:Category {name: $category_name})
            RETURN c
            """
            neo4j_conn.execute_query(category_query, {"category_name": category_name})
            
            # Process each article with its actual source
            new_articles_count = 0
            sources_created = set()
            
            for article in articles:
                actual_source_name = article.get('actual_source', 'Unknown Source')
                retrieved_via = article.get('retrieved_via', None)
                
                # Create the actual source node if not already created in this batch
                if actual_source_name not in sources_created:
                    source_query = """
                    MERGE (s:Source {name: $source_name})
                    ON CREATE SET s.created_at = datetime()
                    RETURN s
                    """
                    neo4j_conn.execute_query(source_query, {"source_name": actual_source_name})
                    
                    # Connect Category to Source
                    category_source_query = """
                    MATCH (c:Category {name: $category_name})
                    MATCH (s:Source {name: $source_name})
                    MERGE (c)-[:HAS_SOURCE]->(s)
                    """
                    neo4j_conn.execute_query(category_source_query, {
                        "category_name": category_name,
                        "source_name": actual_source_name
                    })
                    
                    sources_created.add(actual_source_name)
                
                # Final safety check if article already exists (checking both URLs)
                check_article_query = """
                MATCH (s:Source {name: $source_name})
                MATCH (s)-[:PUBLISHED]->(a:Article)
                WHERE a.url = $url OR a.rss_url = $rss_url
                RETURN a
                """
                existing = neo4j_conn.execute_query(check_article_query, {
                    "source_name": actual_source_name,
                    "url": article['url'],
                    "rss_url": article['rss_url']
                })
                
                if not existing:  # Only create if doesn't exist
                    # Check if this is a TLDR article
                    if retrieved_via == 'TLDR':
                        article_query = """
                        MATCH (s:Source {name: $source_name})
                        CREATE (a:Article {
                            title: $title,
                            content: $content,
                            tldr_summary: $tldr_summary,
                            date: $date,
                            url: $url,
                            rss_url: $rss_url,
                            isRelevant: $isRelevant,
                            retrieved_via: $retrieved_via
                        })
                        CREATE (s)-[:PUBLISHED]->(a)
                        RETURN a
                        """
                        neo4j_conn.execute_query(article_query, {
                            "source_name": actual_source_name,
                            "title": article['title'],
                            "content": article['content'],
                            "tldr_summary": article['tldr_summary'],
                            "date": article['date'],
                            "url": article['url'],
                            "rss_url": article['rss_url'],
                            "isRelevant": article['isRelevant'],
                            "retrieved_via": retrieved_via
                        })
                    else:
                        # Regular article (may or may not have retrieved_via)
                        article_properties = {
                            "source_name": actual_source_name,
                            "title": article['title'],
                            "content": article['content'],
                            "rss_content": article['rss_content'],
                            "date": article['date'],
                            "url": article['url'],
                            "rss_url": article['rss_url'],
                            "isRelevant": article['isRelevant']
                        }
                        
                        if retrieved_via:
                            article_query = """
                            MATCH (s:Source {name: $source_name})
                            CREATE (a:Article {
                                title: $title,
                                content: $content,
                                rss_content: $rss_content,
                                date: $date,
                                url: $url,
                                rss_url: $rss_url,
                                isRelevant: $isRelevant,
                                retrieved_via: $retrieved_via
                            })
                            CREATE (s)-[:PUBLISHED]->(a)
                            RETURN a
                            """
                            article_properties['retrieved_via'] = retrieved_via
                        else:
                            article_query = """
                            MATCH (s:Source {name: $source_name})
                            CREATE (a:Article {
                                title: $title,
                                content: $content,
                                rss_content: $rss_content,
                                date: $date,
                                url: $url,
                                rss_url: $rss_url,
                                isRelevant: $isRelevant
                            })
                            CREATE (s)-[:PUBLISHED]->(a)
                            RETURN a
                            """
                        
                        neo4j_conn.execute_query(article_query, article_properties)
                    
                    new_articles_count += 1
                else:
                    print(f"[Thread {threading.current_thread().name}] Article already exists in database (final check): {article['title'][:50]}...")
            
            print(f"[Thread {threading.current_thread().name}] Successfully stored {new_articles_count} new articles from {aggregator_name} (total processed: {len(articles)})")
            print(f"[Thread {threading.current_thread().name}] Created/updated {len(sources_created)} unique sources")
            return new_articles_count
            
        except Exception as e:
            print(f"[Thread {threading.current_thread().name}] Error creating Neo4j nodes for {aggregator_name}: {e}")
            raise e
    
    def process_single_feed(self, category_name, source_name, source_url, days_back, neo4j_conn):
        """Process a single RSS feed - designed for multithreading"""
        try:
            print(f"[Thread {threading.current_thread().name}] Processing {source_name} from category {category_name} with {self.max_article_workers} article workers")
            
            # Get all existing article URLs to avoid reprocessing
            existing_urls = self.get_existing_article_urls(neo4j_conn)
            
            # Parse RSS feed for articles from last N days (articles processed concurrently)
            articles = self.parse_rss_feed(source_name, source_url, days_back=days_back, existing_urls=existing_urls)
            
            articles_count = 0
            if articles:
                # Store in Neo4j
                articles_count = self.create_neo4j_nodes_and_relationships(
                    neo4j_conn, category_name, source_name, source_url, articles
                )
                print(f"[Thread {threading.current_thread().name}] Successfully processed {source_name}: {articles_count} new articles")
            else:
                print(f"[Thread {threading.current_thread().name}] No new articles found for {source_name}")
            
            return {
                'source_name': source_name,
                'category_name': category_name,
                'articles_count': articles_count,
                'total_articles_found': len(articles),
                'success': True,
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Error processing {source_name}: {e}"
            print(f"[Thread {threading.current_thread().name}] {error_msg}")
            return {
                'source_name': source_name,
                'category_name': category_name,
                'articles_count': 0,
                'total_articles_found': 0,
                'success': False,
                'error': error_msg
            }
    
    def process_all_feeds(self, days_back=1):
        """Main function to scrape RSS feeds and store in Neo4j using multithreading at both feed and article levels"""
        # Load RSS feeds configuration
        rss_config = self.load_rss_feeds()
        
        # Initialize Neo4j connection (thread-safe)
        neo4j_conn = Neo4jConnection(self.neo4j_url, self.neo4j_user, self.neo4j_password)
        
        try:
            # Reset counters
            self._total_articles = 0
            self._processed_sources = 0
            self._total_articles_processed = 0
            self._skipped_articles = 0
            self._fact_extracted_articles = 0
            
            # Prepare list of all feeds to process
            feeds_to_process = []
            for feed_category in rss_config.get('feeds', []):
                category_name = feed_category['category']
                for source in feed_category['sources']:
                    feeds_to_process.append({
                        'category_name': category_name,
                        'source_name': source['name'],
                        'source_url': source['url']
                    })
            
            print(f"Starting multithreaded processing of {len(feeds_to_process)} feeds with {self.max_feed_workers} feed workers and {self.max_article_workers} article workers per feed")
            
            # Process feeds using ThreadPoolExecutor
            results = []
            with ThreadPoolExecutor(max_workers=self.max_feed_workers) as executor:
                # Submit all tasks
                future_to_feed = {
                    executor.submit(
                        self.process_single_feed,
                        feed['category_name'],
                        feed['source_name'],
                        feed['source_url'],
                        days_back,
                        neo4j_conn
                    ): feed for feed in feeds_to_process
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_feed):
                    feed = future_to_feed[future]
                    try:
                        result = future.result()
                        results.append(result)
                        
                        # Update counters
                        if result['success']:
                            self.increment_counters(
                                articles_count=result['articles_count'],
                                sources_count=1
                            )
                        
                        print(f"Completed processing {result['source_name']}: {result['articles_count']} new articles (found {result['total_articles_found']} total)")
                        
                    except Exception as e:
                        error_msg = f"Exception occurred processing {feed['source_name']}: {e}"
                        print(error_msg)
                        results.append({
                            'source_name': feed['source_name'],
                            'category_name': feed['category_name'],
                            'articles_count': 0,
                            'total_articles_found': 0,
                            'success': False,
                            'error': error_msg
                        })
            
            # After all feeds are processed, extract facts from relevant articles
            print("\n=== Starting fact extraction phase ===")
            fact_extraction_count = self.process_fact_extraction_for_relevant_articles(neo4j_conn)
            print(f"=== Completed fact extraction: {fact_extraction_count} articles processed ===\n")

            # After fact extraction, score all sources
            source_scoring_count = self.process_source_scoring(neo4j_conn)
            
            # Get final counters
            total_articles, processed_sources, total_articles_processed, skipped_articles, fact_extracted_articles = self.get_counters()
            
            # Calculate success/failure stats
            successful_sources = sum(1 for r in results if r['success'])
            failed_sources = len(results) - successful_sources
            total_articles_found = sum(r['total_articles_found'] for r in results)
            
            if failed_sources > 0:
                print(f"Processing completed with some failures: {successful_sources} successful, {failed_sources} failed")
                for result in results:
                    if not result['success']:
                        print(f"Failed: {result['source_name']} - {result['error']}")
            
            result = {
                "total_articles": total_articles,
                "processed_sources": processed_sources,
                "successful_sources": successful_sources,
                "failed_sources": failed_sources,
                "total_articles_found": total_articles_found,
                "total_articles_processed": total_articles_processed,
                "skipped_articles": skipped_articles,
                "fact_extracted_articles": fact_extraction_count,
                "sources_scored": source_scoring_count,  # Add this line
                "success": True,
                "message": f"Successfully processed {total_articles} articles from {processed_sources} sources ({successful_sources} successful, {failed_sources} failed). Found {total_articles_found} total articles, processed {total_articles_processed} individual articles, skipped {skipped_articles} already existing articles. Extracted facts from {fact_extraction_count} relevant articles. Scored {source_scoring_count} sources.",  # Update this message
                "detailed_results": results,
                "performance_stats": {
                    "feed_workers": self.max_feed_workers,
                    "article_workers_per_feed": self.max_article_workers,
                    "total_potential_article_workers": self.max_feed_workers * self.max_article_workers
                }
            }
            
            print(result["message"])
            return result
            
        except Exception as e:
            error_result = {
                "total_articles": 0,
                "processed_sources": 0,
                "successful_sources": 0,
                "failed_sources": 0,
                "total_articles_found": 0,
                "total_articles_processed": 0,
                "skipped_articles": 0,
                "fact_extracted_articles": 0,
                "sources_scored": 0,  # Add this line
                "success": False,
                "message": f"Error in process_all_feeds: {e}",
                "detailed_results": [],
                "performance_stats": {
                    "feed_workers": self.max_feed_workers,
                    "article_workers_per_feed": self.max_article_workers,
                    "total_potential_article_workers": self.max_feed_workers * self.max_article_workers
                }
            }
            print(error_result["message"])
            return error_result
            
        finally:
            neo4j_conn.close()

def create_feed_processor(neo4j_url, neo4j_user, neo4j_password, max_feed_workers=5, max_article_workers=3):
    """Factory function to create RSS Feed Processor with configurable thread counts"""
    return RSSFeedProcessor(neo4j_url, neo4j_user, neo4j_password, max_feed_workers=max_feed_workers, max_article_workers=max_article_workers)