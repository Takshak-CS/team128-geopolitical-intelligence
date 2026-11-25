"""User analytics: page views, clicks, and query submissions.

Stored in SQLite (ANALYTICS_DB, default data/analytics.db) on the same
Docker volume as reviews, so events survive redeploys.

Events have a type (page_view, click, query_submit, …), a page, and an
optional label (button name, country clicked, etc.). The visitor IP is
hashed before storage and never stored in plain text.

    python -m app.analytics summary        counts by event type and page
    python -m app.analytics export         all rows as CSV on stdout
"""

from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_lock = threading.Lock()

EVENT_TYPES = {
    "page_view", "click", "query_submit", "country_click",
    "agent_card_click", "dashboard_visit", "case_study_section",
}

COLUMNS = ["id", "created_at", "page", "event", "label", "visitor_hash"]


def db_path() -> Path:
    return Path(os.environ.get("ANALYTICS_DB", "data/analytics.db"))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at   TEXT    NOT NULL,
            page         TEXT    NOT NULL,
            event        TEXT    NOT NULL,
            label        TEXT    NOT NULL DEFAULT '',
            visitor_hash TEXT    NOT NULL DEFAULT ''
        )
    """)
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _hash_visitor(ip: str) -> str:
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def record(page: str, event: str, label: str = "", visitor_ip: str = "") -> int:
    """Insert one event row; returns the new row id."""
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    visitor_hash = _hash_visitor(visitor_ip) if visitor_ip else ""
    with _lock, _db() as conn:
        cursor = conn.execute(
            "INSERT INTO events (created_at, page, event, label, visitor_hash) VALUES (?,?,?,?,?)",
            (created, page[:64], event[:64], label[:128], visitor_hash),
        )
        return cursor.lastrowid


def summary() -> dict:
    """Aggregate counts — safe to expose publicly."""
    with _lock, _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        by_page = {
            row[0]: row[1]
            for row in conn.execute("SELECT page, COUNT(*) FROM events GROUP BY page ORDER BY COUNT(*) DESC")
        }
        by_event = {
            row[0]: row[1]
            for row in conn.execute("SELECT event, COUNT(*) FROM events GROUP BY event ORDER BY COUNT(*) DESC")
        }
        # unique visitors (distinct hashes, excluding empty)
        unique = conn.execute(
            "SELECT COUNT(DISTINCT visitor_hash) FROM events WHERE visitor_hash != ''"
        ).fetchone()[0]
        # page views only
        views = conn.execute("SELECT COUNT(*) FROM events WHERE event='page_view'").fetchone()[0]
        # last 7 days daily views
        daily = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT substr(created_at,1,10) as d, COUNT(*) FROM events "
                "WHERE event='page_view' AND created_at >= datetime('now','-7 days') "
                "GROUP BY d ORDER BY d"
            )
        }
        # top clicked labels
        top_clicks = [
            {"label": row[0], "count": row[1]}
            for row in conn.execute(
                "SELECT label, COUNT(*) FROM events WHERE event='click' AND label != '' "
                "GROUP BY label ORDER BY COUNT(*) DESC LIMIT 10"
            )
        ]
        # top countries clicked on globe
        top_countries = [
            {"country": row[0], "count": row[1]}
            for row in conn.execute(
                "SELECT label, COUNT(*) FROM events WHERE event='country_click' AND label != '' "
                "GROUP BY label ORDER BY COUNT(*) DESC LIMIT 10"
            )
        ]
        # query count
        queries = conn.execute("SELECT COUNT(*) FROM events WHERE event='query_submit'").fetchone()[0]

    return {
        "total_events": total,
        "unique_visitors": unique,
        "page_views": views,
        "queries_submitted": queries,
        "by_page": by_page,
        "by_event": by_event,
        "daily_views_7d": daily,
        "top_clicks": top_clicks,
        "top_countries": top_countries,
    }


def all_events(limit: int = 2000) -> list[dict]:
    with _lock, _db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def export_csv(out=sys.stdout) -> int:
    rows = all_events(limit=100_000)
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    command: Optional[str] = sys.argv[1] if len(sys.argv) > 1 else None
    if command == "export":
        export_csv()
    elif command == "summary":
        import json
        print(json.dumps(summary(), indent=2))
    else:
        print(__doc__)
