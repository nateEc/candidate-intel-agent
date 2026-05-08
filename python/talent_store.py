from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from import_run_sqlite import create_schema


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS application_scan_runs (
          id TEXT PRIMARY KEY,
          job_filter TEXT,
          status TEXT NOT NULL DEFAULT 'running',
          candidate_count INTEGER NOT NULL DEFAULT 0,
          application_count INTEGER NOT NULL DEFAULT 0,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          raw_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS candidate_identity_links (
          identity_key TEXT PRIMARY KEY,
          source_fingerprint TEXT NOT NULL,
          confidence REAL,
          basis_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_applications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          application_key TEXT NOT NULL UNIQUE,
          source_fingerprint TEXT NOT NULL,
          scan_run_id TEXT,
          job_title TEXT,
          job_filter TEXT,
          candidate_name TEXT,
          chat_status TEXT,
          last_message TEXT,
          message_time TEXT,
          observed_at TEXT NOT NULL,
          raw_json TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_applications_fingerprint ON candidate_applications(source_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_candidate_applications_job ON candidate_applications(job_title);
        CREATE INDEX IF NOT EXISTS idx_candidate_applications_scan ON candidate_applications(scan_run_id);

        CREATE TABLE IF NOT EXISTS candidate_evaluations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_fingerprint TEXT NOT NULL,
          application_key TEXT,
          job_title TEXT,
          grade TEXT NOT NULL,
          score INTEGER NOT NULL,
          reasons_json TEXT NOT NULL DEFAULT '[]',
          risks_json TEXT NOT NULL DEFAULT '[]',
          recommended_action TEXT,
          evaluator_version TEXT,
          evaluated_at TEXT NOT NULL,
          raw_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_evaluations_fingerprint ON candidate_evaluations(source_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_candidate_evaluations_grade ON candidate_evaluations(grade);

        CREATE TABLE IF NOT EXISTS candidate_interactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_fingerprint TEXT NOT NULL,
          interaction_type TEXT NOT NULL,
          job_title TEXT,
          message_text TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          raw_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_interactions_fingerprint ON candidate_interactions(source_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_candidate_interactions_type ON candidate_interactions(interaction_type);
        """
    )
    conn.commit()


def create_scan_run(conn: sqlite3.Connection, job_filter: str | None, raw: dict[str, Any] | None = None) -> str:
    scan_id = "appscan_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + hash_text(utc_now())[:8]
    conn.execute(
        """
        INSERT INTO application_scan_runs (id, job_filter, status, started_at, raw_json)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (scan_id, job_filter, utc_now(), as_json(raw or {})),
    )
    conn.commit()
    return scan_id


def finish_scan_run(
    conn: sqlite3.Connection,
    scan_id: str,
    status: str,
    candidate_count: int,
    application_count: int,
    raw: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE application_scan_runs
        SET status=?, candidate_count=?, application_count=?, finished_at=?, raw_json=?
        WHERE id=?
        """,
        (status, candidate_count, application_count, utc_now(), as_json(raw or {}), scan_id),
    )
    conn.commit()


def get_scan_run(conn: sqlite3.Connection, scan_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM application_scan_runs WHERE id=?", (scan_id,)).fetchone()
    return decode_row(row) if row else None


def upsert_application_candidate(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    application: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
    resume_snapshot: dict[str, Any] | None = None,
) -> str:
    candidate = dict(candidate)
    application = dict(application)
    fingerprint = resolve_fingerprint(conn, candidate, application, resume_snapshot)
    candidate["source_fingerprint"] = fingerprint
    upsert_candidate(conn, candidate)
    if resume_snapshot and resume_snapshot.get("resume_text"):
        insert_resume_snapshot(conn, fingerprint, resume_snapshot, candidate.get("source_url"))
    application_key = upsert_application(conn, fingerprint, application)
    application["application_key"] = application_key
    if evaluation:
        insert_evaluation(conn, fingerprint, application, evaluation)
    conn.commit()
    return fingerprint


def resolve_fingerprint(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    application: dict[str, Any],
    resume_snapshot: dict[str, Any] | None,
) -> str:
    identity = build_identity(candidate, application, resume_snapshot)
    row = conn.execute("SELECT source_fingerprint FROM candidate_identity_links WHERE identity_key=?", (identity["identity_key"],)).fetchone()
    if row:
        return str(row["source_fingerprint"])

    fingerprint = candidate.get("source_fingerprint") or hash_text(identity["identity_key"])[:24]
    now = utc_now()
    conn.execute(
        """
        INSERT INTO candidate_identity_links (
          identity_key, source_fingerprint, confidence, basis_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (identity["identity_key"], fingerprint, identity["confidence"], as_json(identity["basis"]), now, now),
    )
    return fingerprint


def build_identity(
    candidate: dict[str, Any],
    application: dict[str, Any],
    resume_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resume_hash = (resume_snapshot or {}).get("resume_text_hash") or candidate.get("resume_text_hash")
    basis = {
        "name": normalize(candidate.get("masked_name") or candidate.get("candidate_name")),
        "age": normalize(candidate.get("age")),
        "education": normalize(candidate.get("education_level")),
        "job": normalize(application.get("job_title") or candidate.get("expected_position")),
        "resume_text_hash": resume_hash,
        "chat_summary_hash": hash_text(application.get("last_message") or "")[:16] if application.get("last_message") else None,
    }
    if resume_hash:
        key_parts = ["resume", basis["name"], basis["age"], basis["education"], basis["job"], str(resume_hash)[:24]]
        confidence = 0.92
    else:
        key_parts = ["weak", basis["name"], basis["age"], basis["education"], basis["job"], basis["chat_summary_hash"]]
        confidence = 0.62
    return {"identity_key": hash_text("|".join(str(item or "") for item in key_parts)), "confidence": confidence, "basis": basis}


def upsert_candidate(conn: sqlite3.Connection, candidate: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO candidates (
          source_fingerprint, source_platform, masked_name, age, years_experience,
          education_level, school, expected_city, expected_position, expected_salary,
          job_status, active_status, short_summary, tags_json, source_url, last_seen_at,
          detail_summary, detail_tags_json, detail_schools_json, detail_companies_json,
          detail_positions_json, parsed_confidence, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source_fingerprint) DO UPDATE SET
          masked_name=COALESCE(excluded.masked_name, candidates.masked_name),
          age=COALESCE(excluded.age, candidates.age),
          years_experience=COALESCE(excluded.years_experience, candidates.years_experience),
          education_level=COALESCE(excluded.education_level, candidates.education_level),
          school=COALESCE(excluded.school, candidates.school),
          expected_city=COALESCE(excluded.expected_city, candidates.expected_city),
          expected_position=COALESCE(excluded.expected_position, candidates.expected_position),
          expected_salary=COALESCE(excluded.expected_salary, candidates.expected_salary),
          job_status=COALESCE(excluded.job_status, candidates.job_status),
          active_status=COALESCE(excluded.active_status, candidates.active_status),
          short_summary=COALESCE(excluded.short_summary, candidates.short_summary),
          tags_json=excluded.tags_json,
          source_url=COALESCE(excluded.source_url, candidates.source_url),
          last_seen_at=COALESCE(excluded.last_seen_at, candidates.last_seen_at),
          detail_summary=COALESCE(excluded.detail_summary, candidates.detail_summary),
          detail_tags_json=excluded.detail_tags_json,
          detail_schools_json=excluded.detail_schools_json,
          detail_companies_json=excluded.detail_companies_json,
          detail_positions_json=excluded.detail_positions_json,
          parsed_confidence=COALESCE(excluded.parsed_confidence, candidates.parsed_confidence),
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            candidate.get("source_fingerprint"),
            candidate.get("source_platform", "boss_zhipin"),
            candidate.get("masked_name") or candidate.get("candidate_name"),
            candidate.get("age"),
            candidate.get("years_experience"),
            candidate.get("education_level"),
            candidate.get("school"),
            candidate.get("expected_city"),
            candidate.get("expected_position"),
            candidate.get("expected_salary"),
            candidate.get("job_status"),
            candidate.get("active_status"),
            candidate.get("short_summary"),
            as_json(candidate.get("tags_json", [])),
            candidate.get("source_url"),
            candidate.get("last_seen_at") or utc_now(),
            candidate.get("detail_summary"),
            as_json(candidate.get("detail_tags_json", [])),
            as_json(candidate.get("detail_schools_json", [])),
            as_json(candidate.get("detail_companies_json", [])),
            as_json(candidate.get("detail_positions_json", [])),
            candidate.get("parsed_confidence"),
        ),
    )


def insert_resume_snapshot(
    conn: sqlite3.Connection,
    fingerprint: str,
    snapshot: dict[str, Any],
    source_url: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO candidate_resume_snapshots (
          source_platform, source_fingerprint, collected_at, source_url, parser_version,
          resume_text, resume_text_hash, resume_sections_json, detail_summary,
          detail_tags_json, detail_schools_json, detail_companies_json, detail_positions_json,
          ocr_engine, ocr_pages_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.get("source_platform", "boss_zhipin"),
            fingerprint,
            snapshot.get("collected_at") or utc_now(),
            snapshot.get("source_url") or source_url,
            snapshot.get("parser_version", "resume_ocr_v1"),
            snapshot.get("resume_text"),
            snapshot.get("resume_text_hash"),
            as_json(snapshot.get("resume_sections_json", {})),
            snapshot.get("detail_summary"),
            as_json(snapshot.get("detail_tags_json", [])),
            as_json(snapshot.get("detail_schools_json", [])),
            as_json(snapshot.get("detail_companies_json", [])),
            as_json(snapshot.get("detail_positions_json", [])),
            snapshot.get("ocr_engine"),
            as_json(snapshot.get("ocr_pages_json", [])),
        ),
    )


def upsert_application(conn: sqlite3.Connection, fingerprint: str, application: dict[str, Any]) -> str:
    application_key = application.get("application_key") or hash_text(
        "|".join(
            [
                fingerprint,
                normalize(application.get("job_title")),
                normalize(application.get("job_filter")),
                normalize(application.get("last_message")),
            ]
        )
    )
    now = utc_now()
    conn.execute(
        """
        INSERT INTO candidate_applications (
          application_key, source_fingerprint, scan_run_id, job_title, job_filter,
          candidate_name, chat_status, last_message, message_time, observed_at,
          raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(application_key) DO UPDATE SET
          source_fingerprint=excluded.source_fingerprint,
          scan_run_id=excluded.scan_run_id,
          job_title=excluded.job_title,
          job_filter=excluded.job_filter,
          candidate_name=excluded.candidate_name,
          chat_status=excluded.chat_status,
          last_message=excluded.last_message,
          message_time=excluded.message_time,
          observed_at=excluded.observed_at,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        (
            application_key,
            fingerprint,
            application.get("scan_run_id"),
            application.get("job_title"),
            application.get("job_filter"),
            application.get("candidate_name"),
            application.get("chat_status"),
            application.get("last_message"),
            application.get("message_time"),
            application.get("observed_at") or now,
            as_json(application),
            now,
        ),
    )
    return application_key


def insert_evaluation(
    conn: sqlite3.Connection,
    fingerprint: str,
    application: dict[str, Any],
    evaluation: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO candidate_evaluations (
          source_fingerprint, application_key, job_title, grade, score,
          reasons_json, risks_json, recommended_action, evaluator_version,
          evaluated_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fingerprint,
            application.get("application_key"),
            application.get("job_title"),
            evaluation.get("grade"),
            int(evaluation.get("score") or 0),
            as_json(evaluation.get("reasons", [])),
            as_json(evaluation.get("risks", [])),
            evaluation.get("recommended_action"),
            evaluation.get("evaluator_version"),
            utc_now(),
            as_json(evaluation),
        ),
    )


def record_interaction(
    conn: sqlite3.Connection,
    source_fingerprint: str,
    interaction_type: str,
    status: str,
    job_title: str | None = None,
    message_text: str | None = None,
    raw: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO candidate_interactions (
          source_fingerprint, interaction_type, job_title, message_text, status, created_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source_fingerprint, interaction_type, job_title, message_text, status, utc_now(), as_json(raw or {})),
    )
    conn.commit()
    return int(cursor.lastrowid)


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("raw_json", "basis_json", "reasons_json", "risks_json"):
        if key in result:
            result[key] = json_loads(result[key], {} if key.endswith("json") else [])
    return result


def json_loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def hash_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").strip().lower().encode("utf-8")).hexdigest()


def normalize(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()
