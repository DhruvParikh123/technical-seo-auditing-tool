import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_PATH = os.path.join(DB_DIR, "audits.db")

def init_db():
    """Initializes the SQLite database and creates the necessary tables."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audits (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            pages_crawled INTEGER DEFAULT 0,
            summary TEXT,
            pages TEXT,
            error_message TEXT
        )
    """)
    conn.commit()
    conn.close()

def create_audit(audit_id: str, url: str):
    """Creates a new audit record with PENDING status."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    created_at = datetime.utcnow().isoformat() + "Z"
    cursor.execute(
        "INSERT INTO audits (id, url, status, created_at) VALUES (?, ?, ?, ?)",
        (audit_id, url, "pending", created_at)
    )
    conn.commit()
    conn.close()

def update_audit_status(audit_id: str, status: str, error_message: Optional[str] = None):
    """Updates the status and optional error message of an audit."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE audits SET status = ?, error_message = ? WHERE id = ?",
        (status, error_message, audit_id)
    )
    conn.commit()
    conn.close()

def save_audit_results(audit_id: str, pages_crawled: int, summary: Dict[str, Any], pages: list):
    """Saves the complete results of a successful audit and sets status to completed."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE audits SET status = ?, pages_crawled = ?, summary = ?, pages = ? WHERE id = ?",
        ("completed", pages_crawled, json.dumps(summary), json.dumps(pages), audit_id)
    )
    conn.commit()
    conn.close()

def get_audit(audit_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an audit by its ID, parsing JSON summaries and page lists."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audits WHERE id = ?", (audit_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    audit_data = dict(row)
    
    # Parse JSON strings back to python data structures
    if audit_data.get("summary"):
        audit_data["summary"] = json.loads(audit_data["summary"])
    if audit_data.get("pages"):
        audit_data["pages"] = json.loads(audit_data["pages"])
    else:
        audit_data["pages"] = []
        
    return audit_data
