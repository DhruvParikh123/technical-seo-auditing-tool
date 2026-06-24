from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class AuditRequest(BaseModel):
    url: str = Field(..., description="The main URL of the website to audit")

class PageAuditResult(BaseModel):
    url: str
    status_code: int
    title_length: Optional[int] = None
    meta_description_length: Optional[int] = None
    h1_count: int
    canonical_present: bool
    noindex: bool
    page_size_kb: float
    internal_links: int
    issues: List[str]

class AuditSummary(BaseModel):
    missing_title: int = 0
    missing_meta_description: int = 0
    multiple_h1: int = 0
    noindex_pages: int = 0
    non_200_pages: int = 0

class AuditResponse(BaseModel):
    audit_id: str
    url: str
    status: str  # pending, crawling, completed, failed
    created_at: str
    pages_crawled: int = 0
    summary: Optional[AuditSummary] = None
    pages: List[PageAuditResult] = Field(default_factory=list)
    error_message: Optional[str] = None
