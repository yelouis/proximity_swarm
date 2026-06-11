import urllib.request
import urllib.parse
import re
import os

def clean_html(text: str) -> str:
    """Removes HTML tags and decodes common HTML entities."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Replace common HTML entities
    html_entities = {
        "&quot;": '"',
        "&amp;": '&',
        "&lt;": '<',
        "&gt;": '>',
        "&#x27;": "'",
        "&#39;": "'",
        "&nbsp;": " ",
        "&rdquo;": '"',
        "&ldquo;": '"',
        "&mdash;": "-",
    }
    for entity, char in html_entities.items():
        text = text.replace(entity, char)
    return text.strip()

def search_web(query: str, max_results: int = 3, force_mock: bool = False) -> list:
    """
    Searches the web using DuckDuckGo Lite.
    Returns a list of dicts: [{'title': str, 'url': str, 'snippet': str}]
    
    If offline, or if the environment variable PROXIMITY_SWARM_TEST is set,
    or if force_mock=True, returns static mock search results.
    """
    if force_mock or os.environ.get("PROXIMITY_SWARM_TEST") == "1":
        # Return mock results for tests/offline
        return [
            {
                "title": f"Mock Search Result 1 for: {query}",
                "url": "https://example.com/result1",
                "snippet": f"This is a high-quality mock snippet describing Python web search matching query: {query}."
            },
            {
                "title": f"Mock Search Result 2 for: {query}",
                "url": "https://example.com/result2",
                "snippet": "Another relevant mocked search response to ensure the pipeline functions correctly."
            }
        ][:max_results]

    url = "https://lite.duckduckgo.com/lite/"
    # Prepare form data
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        # 10s timeout to prevent hanging the runner
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            
            # Find class='result-link' links and class='result-snippet' snippet rows
            links_titles = re.findall(
                r"<a[^>]*href=\"([^\"]+)\"[^>]*class='result-link'[^>]*>(.*?)</a>", 
                html, 
                re.DOTALL
            )
            snippets = re.findall(
                r"<td[^>]*class='result-snippet'[^>]*>(.*?)</td>", 
                html, 
                re.DOTALL
            )
            
            results = []
            limit = min(len(links_titles), len(snippets), max_results)
            for i in range(limit):
                raw_url, raw_title = links_titles[i]
                raw_snippet = snippets[i]
                
                # Clean elements
                title = clean_html(raw_title)
                snippet = clean_html(raw_snippet)
                
                # Unquote URL redirect if needed (DDG lite URLs sometimes are direct, sometimes redirects)
                res_url = raw_url
                if "uddg=" in raw_url:
                    parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                    if "uddg" in parsed_qs:
                        res_url = parsed_qs["uddg"][0]
                        
                results.append({
                    "title": title,
                    "url": res_url,
                    "snippet": snippet
                })
                
            if not results:
                # Return empty list or fallback message
                return [{"title": "No results", "url": "", "snippet": "No matching web results found."}]
            return results
            
    except Exception as e:
        # Graceful fallback: return a single entry with the failure diagnostics
        return [{
            "title": "Search Error",
            "url": "",
            "snippet": f"Web search failed dynamically: {str(e)}"
        }]
