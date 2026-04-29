from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"ready", "failed", "blocked_needs_human"}
ACTIVE_STATUSES = {"queued", "running_jobs", "running_candidates", "importing", "generating_report"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def new_job_id() -> str:
    stamp = utc_now().strftime("%Y%m%d%H%M%S")
    return f"orgjob_{stamp}_{uuid.uuid4().hex[:8]}"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS org_intel_jobs (
          id TEXT PRIMARY KEY,
          client_request_id TEXT,
          company_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL DEFAULT '[]',
          mode TEXT NOT NULL DEFAULT 'standard',
          refresh TEXT NOT NULL DEFAULT 'auto',
          status TEXT NOT NULL DEFAULT 'queued',
          current_step TEXT,
          eta_seconds INTEGER,
          eta_at TEXT,
          request_json TEXT NOT NULL DEFAULT '{}',
          error_message TEXT,
          report_id INTEGER,
          report_path TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          started_at TEXT,
          finished_at TEXT,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_org_intel_jobs_company ON org_intel_jobs(company_name);
        CREATE INDEX IF NOT EXISTS idx_org_intel_jobs_status ON org_intel_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_org_intel_jobs_created_at ON org_intel_jobs(created_at);

        CREATE TABLE IF NOT EXISTS org_intel_job_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL,
          run_type TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          command TEXT,
          run_file TEXT,
          row_count INTEGER,
          started_at TEXT,
          finished_at TEXT,
          error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_org_intel_job_runs_job_id ON org_intel_job_runs(job_id);

        CREATE TABLE IF NOT EXISTS org_intel_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL DEFAULT '[]',
          report_type TEXT NOT NULL DEFAULT 'single_company',
          report_markdown TEXT NOT NULL,
          source_counts_json TEXT NOT NULL DEFAULT '{}',
          generated_at TEXT,
          report_path TEXT
        );

        CREATE TABLE IF NOT EXISTS org_findings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_name TEXT NOT NULL,
          finding_type TEXT NOT NULL,
          title TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'medium',
          confidence REAL,
          summary TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          generated_at TEXT,
          report_id INTEGER
        );
        """
    )
    conn.commit()


def create_job(conn: sqlite3.Connection, payload: dict[str, Any], eta_seconds: int) -> dict[str, Any]:
    now = utc_now()
    job_id = new_job_id()
    eta_at = now + timedelta(seconds=eta_seconds)
    conn.execute(
        """
        INSERT INTO org_intel_jobs (
          id, client_request_id, company_name, aliases_json, mode, refresh, status,
          current_step, eta_seconds, eta_at, request_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            payload.get("client_request_id"),
            payload["company"],
            json.dumps(payload.get("aliases", []), ensure_ascii=False),
            payload.get("mode", "standard"),
            payload.get("refresh", "auto"),
            "queued",
            "queued",
            eta_seconds,
            eta_at.isoformat(),
            json.dumps(payload, ensure_ascii=False),
            now.isoformat(),
            now.isoformat(),
        ),
    )
    conn.commit()
    return get_job(conn, job_id) or {}


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM org_intel_jobs WHERE id=?", (job_id,)).fetchone()
    return row_to_job(row) if row else None


def get_active_job_for_company(conn: sqlite3.Connection, company: str) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    row = conn.execute(
        f"""
        SELECT * FROM org_intel_jobs
        WHERE company_name=? AND status IN ({placeholders})
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (company, *ACTIVE_STATUSES),
    ).fetchone()
    return row_to_job(row) if row else None


def claim_next_job(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM org_intel_jobs
        WHERE status='queued'
        ORDER BY created_at
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    job = row_to_job(row)
    update_job(conn, job["id"], status="running_jobs", current_step="jobs", started_at=iso_now())
    return get_job(conn, job["id"])


def update_job(conn: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = iso_now()
    assignments = ", ".join(f"{key}=?" for key in fields)
    conn.execute(f"UPDATE org_intel_jobs SET {assignments} WHERE id=?", (*fields.values(), job_id))
    conn.commit()


def append_job_run(
    conn: sqlite3.Connection,
    job_id: str,
    run_type: str,
    status: str,
    command: str | None = None,
    run_file: str | None = None,
    row_count: int | None = None,
    error_message: str | None = None,
) -> None:
    now = iso_now()
    conn.execute(
        """
        INSERT INTO org_intel_job_runs (
          job_id, run_type, status, command, run_file, row_count,
          started_at, finished_at, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, run_type, status, command, run_file, row_count, now, now, error_message),
    )
    conn.commit()


def get_job_runs(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM org_intel_job_runs WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    return [dict(row) for row in rows]


def latest_report_for_company(conn: sqlite3.Connection, company: str, freshness_hours: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM org_intel_reports
        WHERE company_name=?
        ORDER BY generated_at DESC, id DESC
        LIMIT 1
        """,
        (company,),
    ).fetchone()
    if not row:
        return None
    report = dict(row)
    generated_at = parse_datetime(report.get("generated_at"))
    if not generated_at or generated_at < utc_now() - timedelta(hours=freshness_hours):
        return None
    return report


def latest_report_by_id(conn: sqlite3.Connection, report_id: int | None) -> dict[str, Any] | None:
    if not report_id:
        return None
    row = conn.execute("SELECT * FROM org_intel_reports WHERE id=?", (report_id,)).fetchone()
    return dict(row) if row else None


def latest_findings(conn: sqlite3.Connection, company: str, report_id: int | None = None) -> list[dict[str, Any]]:
    if report_id:
        rows = conn.execute("SELECT * FROM org_findings WHERE report_id=? ORDER BY id", (report_id,)).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM org_findings
            WHERE company_name=?
            ORDER BY generated_at DESC, id DESC
            LIMIT 10
            """,
            (company,),
        ).fetchall()
    return [decode_finding(row) for row in rows]


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    job["aliases"] = json_loads(job.pop("aliases_json", "[]"), [])
    job["request"] = json_loads(job.pop("request_json", "{}"), {})
    return job


def decode_finding(row: sqlite3.Row) -> dict[str, Any]:
    finding = dict(row)
    finding["evidence_json"] = json_loads(finding.get("evidence_json"), {})
    return finding


def json_loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
