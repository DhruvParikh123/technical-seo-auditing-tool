import logging
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import asyncio
from typing import List, Set, Dict, Any, Tuple

logger = logging.getLogger("seo_auditor.crawler")

def normalize_url(url: str, base_url: str) -> str:
    """Resolves relative URLs, removes fragments, and normalizes trailing slashes."""
    # Resolve relative URL against base URL
    resolved = urljoin(base_url, url)
    parsed = urlparse(resolved)
    
    # Remove fragment
    cleaned_parsed = parsed._replace(fragment="")
    
    # Reconstruct URL
    normalized = urlunparse(cleaned_parsed)
    
    # Normalize trailing slash for paths (avoiding protocol issues)
    if normalized.endswith("/") and normalized.count("/") > 3:
        normalized = normalized.rstrip("/")
        
    return normalized

def is_same_domain(url: str, base_url: str) -> bool:
    """Checks if the URL is on the same domain or subdomain as base_url."""
    try:
        parsed_url = urlparse(url)
        parsed_base = urlparse(base_url)
        
        # Extract hostnames
        url_host = parsed_url.netloc.lower()
        base_host = parsed_base.netloc.lower()
        
        # Remove 'www.' prefix for comparison
        url_domain = url_host.replace("www.", "")
        base_domain = base_host.replace("www.", "")
        
        return url_domain == base_domain or url_host.endswith("." + base_domain)
    except Exception:
        return False

def extract_navigation_links(html_content: str, base_url: str) -> List[str]:
    """
    Identifies the main navigation menu using BeautifulSoup heuristics and
    extracts deduplicated, same-domain links.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    nav_elements = []

    # 1. Look for semantic <nav> tags
    nav_elements = soup.find_all("nav")
    
    # 2. If no <nav> tags, look for elements with role="navigation"
    if not nav_elements:
        nav_elements = soup.find_all(attrs={"role": "navigation"})
        
    # 3. If still none, look for divs/lists with classes or ids containing nav/menu/header/navbar
    if not nav_elements:
        nav_keywords = ["navbar", "nav", "menu-bar", "main-menu", "primary-menu", "top-menu", "header-menu"]
        exclude_keywords = ["footer", "sidebar", "aside", "widget", "social", "mobile"]
        
        candidates = soup.find_all(["div", "ul", "ol", "header"])
        for candidate in candidates:
            # Check id and class list
            elem_id = candidate.get("id", "")
            if isinstance(elem_id, list):
                elem_id = " ".join(elem_id)
            elem_id = elem_id.lower()
            
            elem_classes = candidate.get("class", [])
            if isinstance(elem_classes, list):
                elem_classes = " ".join(elem_classes)
            elem_classes = elem_classes.lower()
            
            # Match keywords
            has_nav_keyword = any(kw in elem_id or kw in elem_classes for kw in nav_keywords)
            has_exclude_keyword = any(kw in elem_id or kw in elem_classes for kw in exclude_keywords)
            
            if has_nav_keyword and not has_exclude_keyword:
                nav_elements.append(candidate)

    # 4. Fallback to <header> tags if nothing specific was found
    if not nav_elements:
        nav_elements = soup.find_all("header")

    # If nav containers were identified, parse links within them
    nav_links = set()
    if nav_elements:
        logger.info(f"Found {len(nav_elements)} potential navigation containers.")
        for nav in nav_elements:
            for link in nav.find_all("a", href=True):
                href = link["href"].strip()
                if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    norm = normalize_url(href, base_url)
                    if is_same_domain(norm, base_url):
                        nav_links.add(norm)
    else:
        # Extreme Fallback: Parse all same-domain links on page, warning recorded in log
        logger.warning("No main navigation menu identified. Falling back to all same-domain links.")
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            # Ignore clear footer/sidebar/widget links if possible
            parent = link.parent
            is_ignored_parent = False
            while parent:
                parent_id = str(parent.get("id", "")).lower()
                parent_classes = " ".join(parent.get("class", [])) if parent.get("class") else ""
                parent_classes = parent_classes.lower()
                
                if any(kw in parent_id or kw in parent_classes for kw in ["footer", "sidebar", "aside"]):
                    is_ignored_parent = True
                    break
                parent = parent.parent
                
            if is_ignored_parent:
                continue
                
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                norm = normalize_url(href, base_url)
                if is_same_domain(norm, base_url):
                    nav_links.add(norm)

    # Ensure base_url itself is included, or at least its normalized version
    normalized_base = normalize_url("", base_url)
    # Convert back to sorted list for deterministic results
    results = sorted(list(nav_links))
    
    # If the list is empty, make sure we at least audit the homepage
    if not results:
        results = [normalized_base]
        
    return results

async def fetch_page(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    """Fetches a page asynchronously and returns status, content, and size."""
    headers = {
        "User-Agent": "ZensorSEOAuditor/1.0 (+https://zensorsolutions.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        # Standard SEO crawling needs to handle redirects and respect timeouts
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=10.0)
        
        # Check if response is HTML
        content_type = response.headers.get("content-type", "").lower()
        is_html = "text/html" in content_type or "application/xhtml+xml" in content_type
        
        return {
            "url": str(response.url),
            "status_code": response.status_code,
            "html": response.text if is_html else "",
            "headers": dict(response.headers),
            "page_size_kb": len(response.content) / 1024.0,
            "success": True,
            "error": None
        }
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching {url}: {str(e)}")
        return {
            "url": url,
            "status_code": getattr(e.response, "status_code", 0) if hasattr(e, "response") else 0,
            "html": "",
            "headers": {},
            "page_size_kb": 0.0,
            "success": False,
            "error": f"HTTP Error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {str(e)}")
        return {
            "url": url,
            "status_code": 0,
            "html": "",
            "headers": {},
            "page_size_kb": 0.0,
            "success": False,
            "error": f"Connection Error: {str(e)}"
        }
    
# Test execution helper
if __name__ == "__main__":
    # Quick simple test of nav parsing
    test_html = """
    <html>
    <body>
        <header>
            <nav id="main-nav">
                <a href="/">Home</a>
                <a href="/pricing">Pricing</a>
                <a href="https://example.com/about">About Us</a>
                <a href="https://external.com">External Link</a>
            </nav>
        </header>
        <div id="content">
            <a href="/blog/some-article">Read blog post</a>
        </div>
        <footer class="footer-nav">
            <a href="/privacy">Privacy Policy</a>
        </footer>
    </body>
    </html>
    """
    links = extract_navigation_links(test_html, "https://example.com")
    print("Extracted links:", links)
