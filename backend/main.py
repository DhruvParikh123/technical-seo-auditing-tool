import os
import uuid
import logging
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import httpx

from backend.models import AuditRequest, AuditResponse
from backend import database
from backend.crawler import normalize_url, extract_navigation_links, fetch_page
from backend.auditor import audit_page, calculate_summary

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("seo_auditor")

app = FastAPI(title="Technical SEO Auditing Tool API", version="1.0.0")

# Enable CORS for local development environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database on Startup
@app.on_event("startup")
def startup_event():
    database.init_db()
    logger.info("Database initialized successfully.")

# Background Worker for SEO crawling and auditing
async def run_audit_task(audit_id: str, start_url: str):
    logger.info(f"Starting audit background task {audit_id} for URL: {start_url}")
    database.update_audit_status(audit_id, "crawling")
    try:
        normalized_start = normalize_url("", start_url)
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=12.0) as client:
            # 1. Fetch the homepage
            homepage_res = await fetch_page(client, normalized_start)
            if not homepage_res["success"]:
                err_msg = homepage_res.get('error') or f"HTTP {homepage_res['status_code']}"
                raise Exception(f"Failed to fetch homepage: {err_msg}")
            
            if homepage_res["status_code"] != 200:
                # If homepage is non-200, audit it and complete.
                audit_res = audit_page(
                    url=normalized_start,
                    status_code=homepage_res["status_code"],
                    html_content=homepage_res["html"],
                    headers=homepage_res["headers"],
                    page_size_kb=homepage_res["page_size_kb"],
                    base_url=normalized_start
                )
                database.save_audit_results(
                    audit_id=audit_id,
                    pages_crawled=1,
                    summary=calculate_summary([audit_res]),
                    pages=[audit_res]
                )
                logger.info(f"Audit {audit_id} finished. Homepage returned non-200: {homepage_res['status_code']}")
                return

            # 2. Extract primary navigation links
            nav_urls = extract_navigation_links(homepage_res["html"], normalized_start)
            
            # Ensure the homepage itself is present in the links to be audited
            if normalized_start not in nav_urls:
                nav_urls.insert(0, normalized_start)
                
            # Deduplicate while preserving order
            seen = set()
            unique_nav_urls = []
            for u in nav_urls:
                if u not in seen:
                    seen.add(u)
                    unique_nav_urls.append(u)
                    
            logger.info(f"Extracted {len(unique_nav_urls)} unique navigation links to audit: {unique_nav_urls}")
            
            # 3. Audit each extracted page
            audited_pages = []
            for url in unique_nav_urls:
                logger.info(f"Auditing page: {url}")
                
                # Optimize: reuse already fetched homepage HTML to avoid duplicate requests
                if url == normalized_start:
                    page_res = homepage_res
                else:
                    await asyncio.sleep(0.4)  # Polite crawling gap
                    page_res = await fetch_page(client, url)
                
                audit_res = audit_page(
                    url=url,
                    status_code=page_res["status_code"],
                    html_content=page_res["html"],
                    headers=page_res["headers"],
                    page_size_kb=page_res["page_size_kb"],
                    base_url=normalized_start
                )
                audited_pages.append(audit_res)
                
            # 4. Aggregate summaries
            summary = calculate_summary(audited_pages)
            
            # 5. Persist results
            database.save_audit_results(
                audit_id=audit_id,
                pages_crawled=len(audited_pages),
                summary=summary,
                pages=audited_pages
            )
            logger.info(f"Audit {audit_id} successfully completed and saved.")
            
    except Exception as e:
        logger.exception(f"Exception raised in background audit thread {audit_id}: {str(e)}")
        database.update_audit_status(audit_id, "failed", error_message=str(e))

# ----------------- BACKEND API ENDPOINTS -----------------

@app.post("/api/audit", response_model=dict[str, str])
async def start_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
        
    # Prepend schema if user typed a bare domain name
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        
    # Quick schema and host validation
    try:
        parsed = httpx.URL(url)
        if not parsed.host:
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid website URL format provided")
        
    audit_id = str(uuid.uuid4())
    database.create_audit(audit_id, url)
    
    # Schedule the crawl as a FastAPI background task
    background_tasks.add_task(run_audit_task, audit_id, url)
    
    return {"audit_id": audit_id}

@app.get("/api/audit/{audit_id}", response_model=AuditResponse)
async def get_audit_results(audit_id: str):
    audit_record = database.get_audit(audit_id)
    if not audit_record:
        raise HTTPException(status_code=404, detail="Audit job not found")
        
    return AuditResponse(
        audit_id=audit_record["id"],
        url=audit_record["url"],
        status=audit_record["status"],
        created_at=audit_record["created_at"],
        pages_crawled=audit_record["pages_crawled"],
        summary=audit_record["summary"],
        pages=audit_record["pages"],
        error_message=audit_record["error_message"]
    )

# ----------------- MOCK SITE ENDPOINTS -----------------
# Built-in multi-page site specifically structured to test all SEO conditions

MOCK_NAV = """
<nav class="main-nav-bar">
    <ul>
        <li><a href="/mock-site/homepage">Home</a></li>
        <li><a href="/mock-site/pricing">Pricing Page</a></li>
        <li><a href="/mock-site/about">About Team</a></li>
        <li><a href="/mock-site/services">SEO Services</a></li>
        <li><a href="/mock-site/portfolio">Client Work</a></li>
        <li><a href="/mock-site/contact">Get In Touch</a></li>
        <li><a href="/mock-site/broken-link">Broken Link</a></li>
    </ul>
</nav>
"""

MOCK_LAYOUT_START = """
<!DOCTYPE html>
<html lang="en">
<head>
    {head_tags}
</head>
<body>
    <header>
        <div class="logo">Zensor Solutions Mock Site</div>
        {nav}
    </header>
    <main style="padding: 40px; font-family: sans-serif; max-width: 800px; margin: 0 auto;">
"""

MOCK_LAYOUT_END = """
    </main>
    <footer style="margin-top: 100px; padding: 20px; text-align: center; border-top: 1px solid #ddd;">
        <p>&copy; 2026 Zensor Mock Labs. Links in footer are ignored.</p>
        <a href="/mock-site/ignored-footer-link">Privacy Policy</a>
    </footer>
</body>
</html>
"""

@app.get("/mock-site", response_class=HTMLResponse)
@app.get("/mock-site/homepage", response_class=HTMLResponse)
async def mock_homepage():
    head = """
    <title>Zensor Mock Site Homepage - Technical SEO Testing</title>
    <meta name="description" content="This is the mock homepage designed to test navigation link crawling and technical SEO auditing. It points to sub-pages with issues.">
    <link rel="canonical" href="https://localhost:8000/mock-site/homepage">
    """
    body = """
    <h1>Welcome to Zensor SEO Test Site</h1>
    <p>This sandbox environment serves mock web pages to test the technical SEO auditing crawler.</p>
    <p>The primary navigation above contains relative links that point to pages specifically seeded with SEO deficiencies.</p>
    <ul>
        <li><b>Pricing:</b> Title and Meta description are too short.</li>
        <li><b>About:</b> Contains multiple H1 elements.</li>
        <li><b>Services:</b> Declares a "noindex" robots tag.</li>
        <li><b>Portfolio:</b> Delivers a page file size larger than 2MB.</li>
        <li><b>Contact:</b> Completely missing Title, Meta Description, and Canonical tags.</li>
        <li><b>Broken Link:</b> Triggers an internal 500 status code response.</li>
    </ul>
    """
    return MOCK_LAYOUT_START.format(head_tags=head, nav=MOCK_NAV) + body + MOCK_LAYOUT_END

@app.get("/mock-site/pricing", response_class=HTMLResponse)
async def mock_pricing():
    # Title and meta description too short
    head = """
    <title>Pricing</title>
    <meta name="description" content="Cheap plans.">
    <link rel="canonical" href="https://localhost:8000/mock-site/pricing">
    """
    body = """
    <h1>Pricing Plans</h1>
    <p>Check out our enterprise auditing software rates. Simple monthly payments.</p>
    """
    return MOCK_LAYOUT_START.format(head_tags=head, nav=MOCK_NAV) + body + MOCK_LAYOUT_END

@app.get("/mock-site/about", response_class=HTMLResponse)
async def mock_about():
    # Multiple H1 elements
    head = """
    <title>About Us - Meet the Zensor Technical SEO Auditing Development Team</title>
    <meta name="description" content="Learn more about the development team behind Zensor Solutions technical SEO auditing platform. We are dedicated to visual excellence and high performance.">
    <link rel="canonical" href="https://localhost:8000/mock-site/about">
    """
    body = """
    <h1>About Our Company</h1>
    <p>We are a high-quality technology agency.</p>
    <h1>Meet the Team</h1>
    <p>Our group of developers and designers works day and night to build audits.</p>
    """
    return MOCK_LAYOUT_START.format(head_tags=head, nav=MOCK_NAV) + body + MOCK_LAYOUT_END

@app.get("/mock-site/services", response_class=HTMLResponse)
async def mock_services():
    # Indexability check: noindex
    head = """
    <title>Our Enterprise Technical Search Engine Optimization Services</title>
    <meta name="description" content="We provide technical SEO audit audits, crawling solutions, site speed optimization, schema markup audits, and robust indexing control protocols for websites.">
    <meta name="robots" content="noindex, nofollow">
    <link rel="canonical" href="https://localhost:8000/mock-site/services">
    """
    body = """
    <h1>Enterprise SEO Services</h1>
    <p>This page features a noindex directive. It should be flagged as unindexable.</p>
    """
    return MOCK_LAYOUT_START.format(head_tags=head, nav=MOCK_NAV) + body + MOCK_LAYOUT_END

@app.get("/mock-site/portfolio", response_class=HTMLResponse)
async def mock_portfolio():
    # Page size check: > 2MB
    head = """
    <title>Our Portfolio of Audited Sites and Client Success Stories</title>
    <meta name="description" content="Explore client work, case studies, and audit results showing how our SEO crawler helps agencies scale their organic optimization strategies.">
    <link rel="canonical" href="https://localhost:8000/mock-site/portfolio">
    """
    # Generating 2.1 MB of content
    huge_comment = "<!-- " + ("X" * (2 * 1024 * 1024 + 100 * 1024)) + " -->"
    body = f"""
    <h1>Our Client Portfolio</h1>
    <p>This page has a size exceeding 2.1 megabytes due to large embedded content representation.</p>
    {huge_comment}
    """
    return MOCK_LAYOUT_START.format(head_tags=head, nav=MOCK_NAV) + body + MOCK_LAYOUT_END

@app.get("/mock-site/contact", response_class=HTMLResponse)
async def mock_contact():
    # Missing title, meta description, and canonical link
    head = ""
    body = """
    <h1>Contact Us</h1>
    <p>Fill out this form to contact Zensor Solutions developers.</p>
    """
    return MOCK_LAYOUT_START.format(head_tags=head, nav=MOCK_NAV) + body + MOCK_LAYOUT_END

@app.get("/mock-site/broken-link", response_class=HTMLResponse)
async def mock_broken():
    # Non-200 page
    raise HTTPException(status_code=500, detail="Simulated server error for auditing tests")


# ----------------- STATIC FRONTEND ROUTING -----------------

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

@app.get("/", response_class=FileResponse)
async def serve_homepage():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Register static files directory for app.js and styles.css
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
