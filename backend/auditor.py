from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import Dict, Any, List
from backend.crawler import is_same_domain, normalize_url

def audit_page(
    url: str,
    status_code: int,
    html_content: str,
    headers: Dict[str, str],
    page_size_kb: float,
    base_url: str
) -> Dict[str, Any]:
    """
    Evaluates a page for technical SEO rules:
    - Title: length 30-65
    - Meta description: length 70-160
    - H1: exactly 1
    - Canonical link: present
    - Indexability: detects noindex in meta tag or X-Robots-Tag header
    - Status code: check if 200
    - Page size: flag if > 2MB (2048 KB)
    - Internal links: counts total internal links on the page
    """
    issues = []
    
    # 1. HTTP Status Code check
    if status_code != 200:
        issues.append("NON_200_STATUS")
        
    # 2. Page Size check (> 2MB)
    if page_size_kb > 2048.0:
        issues.append("PAGE_SIZE_TOO_LARGE")

    # Initial values in case HTML parsing is skipped (e.g. non-200 or no content)
    title_len = None
    meta_desc_len = None
    h1_count = 0
    canonical_present = False
    noindex = False
    internal_links_count = 0

    # Indexability check from HTTP headers
    # Case-insensitive check for X-Robots-Tag
    x_robots = ""
    for k, v in headers.items():
        if k.lower() == "x-robots-tag":
            x_robots = v.lower()
            break
            
    if "noindex" in x_robots:
        noindex = True

    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 3. Title tag check
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.text.strip()
            title_len = len(title_text)
            if title_len < 30:
                issues.append("TITLE_TOO_SHORT")
            elif title_len > 65:
                issues.append("TITLE_TOO_LONG")
        else:
            title_len = 0
            issues.append("TITLE_MISSING")

        # 4. Meta Description check
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if not meta_desc:
            # Also check case variants just in case
            meta_desc = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "description"})
            
        if meta_desc and meta_desc.get("content"):
            desc_text = meta_desc["content"].strip()
            meta_desc_len = len(desc_text)
            if meta_desc_len < 70:
                issues.append("META_DESCRIPTION_TOO_SHORT")
            elif meta_desc_len > 160:
                issues.append("META_DESCRIPTION_TOO_LONG")
        else:
            meta_desc_len = 0
            issues.append("META_DESCRIPTION_MISSING")

        # 5. H1 check
        h1s = soup.find_all("h1")
        h1_count = len(h1s)
        if h1_count == 0:
            issues.append("H1_MISSING")
        elif h1_count > 1:
            issues.append("MULTIPLE_H1")

        # 6. Canonical check
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            canonical_present = True
        else:
            issues.append("CANONICAL_MISSING")

        # 7. Indexability check from Meta tag
        meta_robots = soup.find("meta", attrs={"name": lambda x: x and x.lower() in ("robots", "googlebot")})
        if meta_robots and meta_robots.get("content"):
            content = meta_robots["content"].lower()
            if "noindex" in content:
                noindex = True
                
        if noindex:
            issues.append("NOINDEX_PAGE")

        # 8. Internal links count
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                norm = normalize_url(href, base_url)
                if is_same_domain(norm, base_url):
                    internal_links_count += 1
    else:
        # If no HTML content is fetched, fill defaults or errors
        issues.append("TITLE_MISSING")
        issues.append("META_DESCRIPTION_MISSING")
        issues.append("H1_MISSING")
        issues.append("CANONICAL_MISSING")
        title_len = 0
        meta_desc_len = 0

    return {
        "url": url,
        "status_code": status_code,
        "title_length": title_len,
        "meta_description_length": meta_desc_len,
        "h1_count": h1_count,
        "canonical_present": canonical_present,
        "noindex": noindex,
        "page_size_kb": round(page_size_kb, 2),
        "internal_links": internal_links_count,
        "issues": issues
    }

def calculate_summary(pages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Aggregates page issues to compute the global audit summary metrics."""
    summary = {
        "missing_title": 0,
        "missing_meta_description": 0,
        "multiple_h1": 0,
        "noindex_pages": 0,
        "non_200_pages": 0
    }
    for page in pages:
        issues = page.get("issues", [])
        if "TITLE_MISSING" in issues:
            summary["missing_title"] += 1
        if "META_DESCRIPTION_MISSING" in issues:
            summary["missing_meta_description"] += 1
        if "MULTIPLE_H1" in issues:
            summary["multiple_h1"] += 1
        if "NOINDEX_PAGE" in issues:
            summary["noindex_pages"] += 1
        if "NON_200_STATUS" in issues:
            summary["non_200_pages"] += 1
            
    return summary
