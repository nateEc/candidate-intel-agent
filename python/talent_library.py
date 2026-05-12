from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised only when dependencies are missing.
    psycopg = None
    dict_row = None


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "talent_library_postgres.sql"
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?86[- ]?)?1[3-9]\d{9}")
WECHAT_RE = re.compile(r"(?:微信|wechat|wx|VX|v信)[:：\s]*([A-Za-z][-_A-Za-z0-9]{5,19})")
SALARY_RE = re.compile(r"(?P<min>\d{1,3})(?:-(?P<max>\d{1,3}))?K(?:[·xX*](?P<months>\d{1,2})薪?)?")
DATE_RANGE_RE = re.compile(r"(?P<start>20\d{2}(?:[./-]\d{1,2})?)\s*(?:-|至|~|—|–)\s*(?P<end>至今|现在|20\d{2}(?:[./-]\d{1,2})?)")
EXTRACTOR_VERSION = "rules_evidence_v1"
EMBEDDING_MODEL = "local_hash_bow_v1"
EMBEDDING_DIMS = 384


def database_url(value: str | None = None) -> str:
    url = value or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for the Postgres smart talent library")
    return url


@contextmanager
def connect(url: str | None = None) -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is required. Install dependencies with .venv/bin/pip install -r requirements.txt")
    with psycopg.connect(database_url(url), row_factory=dict_row) as conn:
        yield conn


def migrate(conn: Any) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def json_loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row or {})


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def ingest_candidate_source(conn: Any, source: dict[str, Any]) -> str:
    """Upsert one normalized candidate source into the Postgres smart library."""
    migrate(conn)
    candidate_id = resolve_candidate_id(conn, source)
    if not candidate_id:
        candidate_id = create_candidate_profile(conn, source)
    else:
        update_candidate_profile(conn, candidate_id, source)

    write_identifiers(conn, candidate_id, source)
    write_raw_source(conn, candidate_id, source)
    resume_version_id = write_resume_version(conn, candidate_id, source)
    write_contacts_from_resume(conn, candidate_id, source, resume_version_id)
    write_legacy_match(conn, candidate_id, source)
    refresh_search_document(conn, candidate_id)
    refresh_embedding(conn, candidate_id)
    audit(conn, "candidate_ingested", "candidate_profile", candidate_id, {"source_type": source.get("source_type")})
    conn.commit()
    return str(candidate_id)


def resolve_candidate_id(conn: Any, source: dict[str, Any]) -> str | None:
    identifiers = candidate_identifier_values(source)
    for identifier_type, identifier_value, _, _ in identifiers:
        row = conn.execute(
            "SELECT candidate_id FROM candidate_identifiers WHERE identifier_type=%s AND identifier_hash=%s",
            (identifier_type, hash_text(normalize(identifier_value))),
        ).fetchone()
        if row:
            return str(row["candidate_id"])
    return None


def create_candidate_profile(conn: Any, source: dict[str, Any]) -> str:
    salary = parse_salary(source.get("expected_salary_text") or source.get("expected_salary"))
    row = conn.execute(
        """
        INSERT INTO candidate_profiles (
          display_name, masked_name, current_title, current_company, work_years_text,
          work_years_value, education_level, school, major, city, expected_position,
          expected_salary_text, expected_salary_min_k, expected_salary_max_k,
          expected_salary_months, expected_annual_salary_min_k, expected_annual_salary_max_k,
          job_status, active_status, highest_grade, highest_score, profile_summary,
          tags_json, source_summary_json, first_seen_at, last_seen_at
        ) VALUES (
          %(display_name)s, %(masked_name)s, %(current_title)s, %(current_company)s,
          %(work_years_text)s, %(work_years_value)s, %(education_level)s, %(school)s,
          %(major)s, %(city)s, %(expected_position)s, %(expected_salary_text)s,
          %(expected_salary_min_k)s, %(expected_salary_max_k)s, %(expected_salary_months)s,
          %(expected_annual_salary_min_k)s, %(expected_annual_salary_max_k)s,
          %(job_status)s, %(active_status)s, %(highest_grade)s, %(highest_score)s,
          %(profile_summary)s, %(tags_json)s::jsonb, %(source_summary_json)s::jsonb,
          COALESCE(%(first_seen_at)s, now()), COALESCE(%(last_seen_at)s, now())
        )
        RETURNING candidate_id
        """,
        profile_params(source, salary),
    ).fetchone()
    return str(row["candidate_id"])


def update_candidate_profile(conn: Any, candidate_id: str, source: dict[str, Any]) -> None:
    salary = parse_salary(source.get("expected_salary_text") or source.get("expected_salary"))
    params = profile_params(source, salary)
    params["candidate_id"] = candidate_id
    conn.execute(
        """
        UPDATE candidate_profiles SET
          display_name=COALESCE(%(display_name)s, display_name),
          masked_name=COALESCE(%(masked_name)s, masked_name),
          current_title=COALESCE(%(current_title)s, current_title),
          current_company=COALESCE(%(current_company)s, current_company),
          work_years_text=COALESCE(%(work_years_text)s, work_years_text),
          work_years_value=COALESCE(%(work_years_value)s, work_years_value),
          education_level=COALESCE(%(education_level)s, education_level),
          school=COALESCE(%(school)s, school),
          major=COALESCE(%(major)s, major),
          city=COALESCE(%(city)s, city),
          expected_position=COALESCE(%(expected_position)s, expected_position),
          expected_salary_text=COALESCE(%(expected_salary_text)s, expected_salary_text),
          expected_salary_min_k=COALESCE(%(expected_salary_min_k)s, expected_salary_min_k),
          expected_salary_max_k=COALESCE(%(expected_salary_max_k)s, expected_salary_max_k),
          expected_salary_months=COALESCE(%(expected_salary_months)s, expected_salary_months),
          expected_annual_salary_min_k=COALESCE(%(expected_annual_salary_min_k)s, expected_annual_salary_min_k),
          expected_annual_salary_max_k=COALESCE(%(expected_annual_salary_max_k)s, expected_annual_salary_max_k),
          job_status=COALESCE(%(job_status)s, job_status),
          active_status=COALESCE(%(active_status)s, active_status),
          highest_grade=CASE
            WHEN COALESCE(%(highest_score)s, 0) > COALESCE(highest_score, 0) THEN %(highest_grade)s
            ELSE highest_grade
          END,
          highest_score=GREATEST(COALESCE(highest_score, 0), COALESCE(%(highest_score)s, 0)),
          profile_summary=COALESCE(%(profile_summary)s, profile_summary),
          tags_json=COALESCE(
            (SELECT jsonb_agg(DISTINCT item) FROM jsonb_array_elements_text(tags_json || %(tags_json)s::jsonb) AS item),
            '[]'::jsonb
          ),
          source_summary_json=source_summary_json || %(source_summary_json)s::jsonb,
          last_seen_at=GREATEST(COALESCE(last_seen_at, '-infinity'::timestamptz), COALESCE(%(last_seen_at)s, now())),
          updated_at=now()
        WHERE candidate_id=%(candidate_id)s
        """,
        params,
    )


def profile_params(source: dict[str, Any], salary: dict[str, int] | None) -> dict[str, Any]:
    tags = unique_strings(json_loads(source.get("tags_json"), []) + json_loads(source.get("detail_tags_json"), []))
    return {
        "display_name": source.get("display_name") or source.get("masked_name") or source.get("candidate_name"),
        "masked_name": source.get("masked_name") or source.get("candidate_name"),
        "current_title": source.get("current_title"),
        "current_company": source.get("current_company") or first_item(source.get("detail_companies_json")),
        "work_years_text": source.get("years_experience") or source.get("work_years_text"),
        "work_years_value": parse_years(source.get("years_experience") or source.get("work_years_text")),
        "education_level": source.get("education_level"),
        "school": source.get("school"),
        "major": source.get("major"),
        "city": source.get("expected_city") or source.get("city"),
        "expected_position": source.get("expected_position"),
        "expected_salary_text": source.get("expected_salary_text") or source.get("expected_salary"),
        "expected_salary_min_k": (salary or {}).get("min_k"),
        "expected_salary_max_k": (salary or {}).get("max_k"),
        "expected_salary_months": (salary or {}).get("months"),
        "expected_annual_salary_min_k": (salary or {}).get("annual_min_k"),
        "expected_annual_salary_max_k": (salary or {}).get("annual_max_k"),
        "job_status": source.get("job_status"),
        "active_status": source.get("active_status"),
        "highest_grade": source.get("grade"),
        "highest_score": source.get("score"),
        "profile_summary": source.get("detail_summary") or source.get("short_summary"),
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "source_summary_json": json.dumps(
            {
                "source_type": source.get("source_type"),
                "source_platform": source.get("source_platform"),
                "source_fingerprint": source.get("source_fingerprint"),
                "application_key": source.get("application_key"),
                "detail_companies_json": json_loads(source.get("detail_companies_json"), []),
                "detail_schools_json": json_loads(source.get("detail_schools_json"), []),
                "detail_positions_json": json_loads(source.get("detail_positions_json"), []),
            },
            ensure_ascii=False,
        ),
        "first_seen_at": source.get("observed_at") or source.get("last_seen_at"),
        "last_seen_at": source.get("last_seen_at") or source.get("observed_at"),
    }


def candidate_identifier_values(source: dict[str, Any]) -> list[tuple[str, str, str, float]]:
    values = []
    if source.get("boss_id"):
        values.append(("boss_id", str(source["boss_id"]), "boss", 0.98))
    if source.get("source_fingerprint"):
        values.append(("boss_source_fingerprint", str(source["source_fingerprint"]), "boss", 0.86))
    if source.get("resume_text_hash"):
        values.append(("resume_text_hash", str(source["resume_text_hash"]), "resume", 0.94))
    for contact in extract_contacts(source.get("resume_text") or ""):
        if contact["contact_type"] == "email":
            values.append(("email_hash", contact["contact_value"], "visible_resume", 0.92))
    weak_basis = "|".join(
        normalize(source.get(key))
        for key in ("masked_name", "age", "education_level", "expected_position", "school")
        if source.get(key) is not None
    )
    if weak_basis:
        values.append(("weak_profile_hash", weak_basis, source.get("source_type") or "unknown", 0.55))
    return values


def write_identifiers(conn: Any, candidate_id: str, source: dict[str, Any]) -> None:
    for identifier_type, identifier_value, source_type, confidence in candidate_identifier_values(source):
        conn.execute(
            """
            INSERT INTO candidate_identifiers (
              candidate_id, identifier_type, identifier_hash, identifier_display,
              source_type, confidence, evidence_json
            ) VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT(identifier_type, identifier_hash) DO UPDATE SET
              candidate_id=EXCLUDED.candidate_id,
              confidence=GREATEST(COALESCE(candidate_identifiers.confidence, 0), EXCLUDED.confidence),
              updated_at=now()
            """,
            (candidate_id, identifier_type, hash_text(normalize(identifier_value)), safe_display_identifier(identifier_type, identifier_value), source_type, confidence),
        )


def write_raw_source(conn: Any, candidate_id: str, source: dict[str, Any]) -> None:
    source_type = source.get("source_type") or "unknown"
    source_key = source.get("source_key") or source.get("application_key") or source.get("source_fingerprint") or hash_text(json.dumps(source, ensure_ascii=False, sort_keys=True))
    raw = {key: value for key, value in source.items() if key != "resume_text"}
    conn.execute(
        """
        INSERT INTO raw_candidate_sources (
          candidate_id, source_type, source_platform, source_key, source_fingerprint,
          collected_at, raw_json
        ) VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()), %s::jsonb)
        ON CONFLICT(source_type, source_key) DO UPDATE SET
          candidate_id=EXCLUDED.candidate_id,
          raw_json=EXCLUDED.raw_json
        """,
        (
            candidate_id,
            source_type,
            source.get("source_platform") or "boss_zhipin",
            source_key,
            source.get("source_fingerprint"),
            source.get("observed_at") or source.get("collected_at"),
            json.dumps(raw, ensure_ascii=False),
        ),
    )


def write_resume_version(conn: Any, candidate_id: str, source: dict[str, Any]) -> int | None:
    if not source.get("resume_text") or not source.get("resume_text_hash"):
        return None
    row = conn.execute(
        """
        INSERT INTO resume_versions (
          candidate_id, source_platform, source_fingerprint, collected_at, source_url,
          parser_version, resume_text, resume_text_hash, resume_sections_json,
          detail_summary, detail_tags_json, detail_schools_json, detail_companies_json,
          detail_positions_json, ocr_engine, ocr_pages_json
        ) VALUES (
          %s, %s, %s, COALESCE(%s, now()), %s, %s, %s, %s, %s::jsonb,
          %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb
        )
        ON CONFLICT(candidate_id, resume_text_hash) DO UPDATE SET collected_at=EXCLUDED.collected_at
        RETURNING resume_version_id
        """,
        (
            candidate_id,
            source.get("source_platform") or "boss_zhipin",
            source.get("source_fingerprint"),
            source.get("resume_collected_at") or source.get("collected_at"),
            source.get("source_url"),
            source.get("parser_version") or "resume_ocr_v1",
            source.get("resume_text"),
            source.get("resume_text_hash"),
            json.dumps(json_loads(source.get("resume_sections_json"), {}), ensure_ascii=False),
            source.get("detail_summary"),
            json.dumps(json_loads(source.get("detail_tags_json"), []), ensure_ascii=False),
            json.dumps(json_loads(source.get("detail_schools_json"), []), ensure_ascii=False),
            json.dumps(json_loads(source.get("detail_companies_json"), []), ensure_ascii=False),
            json.dumps(json_loads(source.get("detail_positions_json"), []), ensure_ascii=False),
            source.get("ocr_engine"),
            json.dumps(json_loads(source.get("ocr_pages_json"), []), ensure_ascii=False),
        ),
    ).fetchone()
    return int(row["resume_version_id"]) if row else None


def write_contacts_from_resume(conn: Any, candidate_id: str, source: dict[str, Any], resume_version_id: int | None) -> None:
    for contact in extract_contacts(source.get("resume_text") or ""):
        evidence_id = write_evidence(conn, candidate_id, resume_version_id, "candidate_contacts", contact["evidence_text"], "contacts", 0.82)
        add_contact(
            conn,
            candidate_id,
            contact["contact_type"],
            contact["contact_value"],
            source_type="visible_resume",
            evidence_span_id=evidence_id,
            confidence=0.82,
            commit=False,
        )


def write_legacy_match(conn: Any, candidate_id: str, source: dict[str, Any]) -> None:
    if not source.get("grade") or source.get("score") is None:
        return
    reasons_json = json.dumps(json_loads(source.get("reasons_json"), []), ensure_ascii=False)
    risks_json = json.dumps(json_loads(source.get("risks_json"), []), ensure_ascii=False)
    evidence_json = json.dumps(
        {
            "source": "legacy_candidate_evaluations",
            "application_key": source.get("application_key"),
            "evaluated_at": source.get("evaluated_at"),
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO candidate_matches (
          candidate_id, job_title, score, grade, reasons_json, risks_json,
          evidence_json, matcher_version
        )
        SELECT %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s
        WHERE NOT EXISTS (
          SELECT 1 FROM candidate_matches
          WHERE candidate_id=%s
            AND COALESCE(job_title, '')=COALESCE(%s, '')
            AND score=%s
            AND grade=%s
            AND reasons_json=%s::jsonb
            AND risks_json=%s::jsonb
            AND matcher_version=%s
        )
        """,
        (
            candidate_id,
            source.get("application_job_title") or source.get("job_filter"),
            int(source.get("score") or 0),
            source.get("grade"),
            reasons_json,
            risks_json,
            evidence_json,
            "legacy_rules_v1",
            candidate_id,
            source.get("application_job_title") or source.get("job_filter"),
            int(source.get("score") or 0),
            source.get("grade"),
            reasons_json,
            risks_json,
            "legacy_rules_v1",
        ),
    )


def ingest_boss_snapshot_from_sqlite(
    conn: Any,
    sqlite_db: Path,
    *,
    scan_run_id: str | None = None,
    source_fingerprint: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    migrate(conn)
    rows = load_sqlite_legacy_candidates(sqlite_db, scan_run_id=scan_run_id, source_fingerprint=source_fingerprint, limit=limit)
    candidate_ids = []
    for row in rows:
        candidate_ids.append(ingest_candidate_source(conn, normalize_legacy_candidate(row)))
    resume_result = ingest_sqlite_resume_versions(
        conn,
        sqlite_db,
        source_fingerprints=[row.get("source_fingerprint") for row in rows if row.get("source_fingerprint")],
    )
    return {
        "status": "ready",
        "count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "resume_versions": resume_result,
    }


def ingest_sqlite_resume_versions(
    conn: Any,
    sqlite_db: Path,
    *,
    source_fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    """Import every OCR/import resume snapshot, not only the latest joined candidate row."""
    if source_fingerprints is not None:
        source_fingerprints = unique_strings(source_fingerprints)
    rows = load_sqlite_resume_snapshots(sqlite_db, source_fingerprints=source_fingerprints)
    touched_candidate_ids: set[str] = set()
    imported = 0
    skipped = 0
    for row in rows:
        candidate_id = candidate_id_for_source_fingerprint(conn, row.get("source_fingerprint"))
        if not candidate_id:
            skipped += 1
            continue
        source = {
            **row,
            "source_type": "boss_resume_snapshot",
            "source_key": f"resume_snapshot:{row.get('id')}",
        }
        write_identifiers(conn, candidate_id, source)
        resume_version_id = write_resume_version(conn, candidate_id, source)
        write_contacts_from_resume(conn, candidate_id, source, resume_version_id)
        touched_candidate_ids.add(candidate_id)
        imported += 1
    for candidate_id in touched_candidate_ids:
        refresh_search_document(conn, candidate_id)
        refresh_embedding(conn, candidate_id)
    conn.commit()
    return {
        "status": "ready",
        "source_rows": len(rows),
        "imported_rows": imported,
        "skipped_rows": skipped,
        "touched_candidates": len(touched_candidate_ids),
    }


def candidate_id_for_source_fingerprint(conn: Any, source_fingerprint: str | None) -> str | None:
    if not source_fingerprint:
        return None
    row = conn.execute(
        """
        SELECT candidate_id
        FROM raw_candidate_sources
        WHERE source_fingerprint=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (source_fingerprint,),
    ).fetchone()
    return str(row["candidate_id"]) if row and row.get("candidate_id") else None


def load_sqlite_resume_snapshots(sqlite_db: Path, *, source_fingerprints: list[str] | None = None) -> list[dict[str, Any]]:
    where_sql = ""
    params: list[Any] = []
    if source_fingerprints:
        placeholders = ",".join("?" for _ in source_fingerprints)
        where_sql = f"WHERE source_fingerprint IN ({placeholders})"
        params.extend(source_fingerprints)
    with sqlite3.connect(sqlite_db) as src:
        src.row_factory = sqlite3.Row
        rows = src.execute(
            f"""
            SELECT *
            FROM candidate_resume_snapshots
            {where_sql}
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def load_sqlite_legacy_candidates(
    sqlite_db: Path,
    *,
    scan_run_id: str | None = None,
    source_fingerprint: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if source_fingerprint:
        where.append("c.source_fingerprint=?")
        params.append(source_fingerprint)
    if scan_run_id:
        where.append("a.scan_run_id=?")
        params.append(scan_run_id)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    with sqlite3.connect(sqlite_db) as src:
        src.row_factory = sqlite3.Row
        rows = src.execute(
            f"""
            SELECT
              c.*,
              a.application_key,
              a.scan_run_id,
              a.job_title AS application_job_title,
              a.job_filter,
              a.last_message,
              a.message_time,
              a.observed_at AS application_observed_at,
              e.grade,
              e.score,
              e.reasons_json,
              e.risks_json,
              e.recommended_action,
              r.collected_at AS resume_collected_at,
              r.resume_text,
              r.resume_text_hash,
              r.resume_sections_json,
              r.ocr_engine,
              r.ocr_pages_json
            FROM candidates c
            LEFT JOIN (
              SELECT * FROM candidate_applications
              WHERE id IN (SELECT MAX(id) FROM candidate_applications GROUP BY source_fingerprint)
            ) a ON a.source_fingerprint=c.source_fingerprint
            LEFT JOIN (
              SELECT * FROM candidate_evaluations
              WHERE id IN (SELECT MAX(id) FROM candidate_evaluations GROUP BY source_fingerprint)
            ) e ON e.source_fingerprint=c.source_fingerprint
            LEFT JOIN (
              SELECT * FROM candidate_resume_snapshots
              WHERE id IN (SELECT MAX(id) FROM candidate_resume_snapshots GROUP BY source_fingerprint)
            ) r ON r.source_fingerprint=c.source_fingerprint
            {where_sql}
            ORDER BY COALESCE(a.updated_at, c.updated_at) DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def normalize_legacy_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "source_type": "boss_application" if row.get("application_key") else "boss_candidate_search",
        "source_key": row.get("application_key") or row.get("source_fingerprint"),
        "expected_salary_text": row.get("expected_salary"),
        "observed_at": row.get("application_observed_at") or row.get("last_seen_at"),
    }


def enrich_candidate(conn: Any, candidate_id: str, extractor_version: str = EXTRACTOR_VERSION) -> dict[str, Any]:
    migrate(conn)
    profile = get_candidate_profile(conn, candidate_id)
    if not profile:
        raise KeyError(f"candidate not found: {candidate_id}")
    resume = latest_resume(conn, candidate_id)
    resume_text = resume.get("resume_text", "") if resume else ""
    resume_version_id = resume.get("resume_version_id") if resume else None
    clear_enrichment(conn, candidate_id, extractor_version)

    tags = unique_strings(
        (profile.get("tags_json") or [])
        + ((resume or {}).get("detail_tags_json") or [])
        + extract_skill_terms(resume_text)
    )
    for skill in tags[:80]:
        evidence_id = write_evidence(conn, candidate_id, resume_version_id, "skills", skill, "skills", 0.7)
        conn.execute(
            """
            INSERT INTO skills (
              candidate_id, skill_name, skill_type, evidence_span_id,
              confidence, extractor_version
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT(candidate_id, skill_name) DO UPDATE SET
              skill_type=EXCLUDED.skill_type,
              confidence=GREATEST(COALESCE(skills.confidence, 0), EXCLUDED.confidence),
              extractor_version=EXCLUDED.extractor_version,
              updated_at=now()
            """,
            (candidate_id, skill, infer_skill_type(skill), evidence_id, 0.7, extractor_version),
        )

    for item in extract_work_experiences(profile, resume):
        conn.execute(
            """
            INSERT INTO work_experiences (
              candidate_id, company_name, title, department, start_date, end_date,
              duration_months, description, tech_stack_json, achievements_json,
              salary_min_k, salary_max_k, evidence_span_id, confidence, extractor_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
            ON CONFLICT(candidate_id, company_name, title, start_date, end_date) DO UPDATE SET
              description=COALESCE(EXCLUDED.description, work_experiences.description),
              updated_at=now()
            """,
            (
                candidate_id,
                item.get("company_name"),
                item.get("title"),
                item.get("department"),
                item.get("start_date"),
                item.get("end_date"),
                item.get("duration_months"),
                item.get("description"),
                json.dumps(item.get("tech_stack", []), ensure_ascii=False),
                json.dumps(item.get("achievements", []), ensure_ascii=False),
                item.get("salary_min_k"),
                item.get("salary_max_k"),
                write_evidence(conn, candidate_id, resume_version_id, "work_experiences", item.get("evidence_text"), "work_experiences", 0.68),
                item.get("confidence", 0.65),
                extractor_version,
            ),
        )

    for item in extract_education(profile, resume):
        conn.execute(
            """
            INSERT INTO education_experiences (
              candidate_id, school, major, degree, start_date, end_date,
              ranking_tags_json, evidence_span_id, confidence, extractor_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT(candidate_id, school, major, degree, start_date, end_date) DO UPDATE SET updated_at=now()
            """,
            (
                candidate_id,
                item.get("school"),
                item.get("major"),
                item.get("degree"),
                item.get("start_date"),
                item.get("end_date"),
                json.dumps(item.get("ranking_tags", []), ensure_ascii=False),
                write_evidence(conn, candidate_id, resume_version_id, "education_experiences", item.get("evidence_text"), "education_experiences", 0.72),
                item.get("confidence", 0.7),
                extractor_version,
            ),
        )

    for item in extract_projects(resume_text):
        conn.execute(
            """
            INSERT INTO projects (
              candidate_id, project_name, role, start_date, end_date, business_context,
              technical_context, outcomes_json, evidence_span_id, confidence, extractor_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                candidate_id,
                item.get("project_name"),
                item.get("role"),
                item.get("start_date"),
                item.get("end_date"),
                item.get("business_context"),
                item.get("technical_context"),
                json.dumps(item.get("outcomes", []), ensure_ascii=False),
                write_evidence(conn, candidate_id, resume_version_id, "projects", item.get("evidence_text"), "projects", 0.55),
                item.get("confidence", 0.55),
                extractor_version,
            ),
        )

    write_compensation(conn, candidate_id, "expected_salary", profile.get("expected_salary_text"), None, "profile", 0.8)
    for salary_text in extract_salary_mentions(resume_text):
        write_compensation(conn, candidate_id, "resume_salary_mention", salary_text, write_evidence(conn, candidate_id, resume_version_id, "compensation", salary_text, "compensation", 0.45), "resume", 0.45)
    for pref_type, pref_value in extract_preferences(profile):
        conn.execute(
            """
            INSERT INTO candidate_preferences (
              candidate_id, preference_type, preference_value, confidence, source_type
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(candidate_id, preference_type, preference_value) DO UPDATE SET updated_at=now()
            """,
            (candidate_id, pref_type, pref_value, 0.75, "profile"),
        )
    for item in extract_sensitive_attributes(resume_text):
        conn.execute(
            """
            INSERT INTO candidate_sensitive_attributes (
              candidate_id, attribute_type, attribute_value, visibility,
              use_allowed_for_matching, use_allowed_for_outreach, evidence_span_id,
              confidence, source_type
            ) VALUES (%s, %s, %s, 'restricted', false, false, %s, %s, 'resume')
            """,
            (
                candidate_id,
                item["attribute_type"],
                item["attribute_value"],
                write_evidence(conn, candidate_id, resume_version_id, "candidate_sensitive_attributes", item["evidence_text"], "sensitive_attributes", 0.55),
                item.get("confidence", 0.55),
            ),
        )
    for signal in generate_signals(conn, candidate_id, profile):
        conn.execute(
            """
            INSERT INTO candidate_signals (
              candidate_id, signal_type, signal_value, score, confidence,
              evidence_json, extractor_version
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT(candidate_id, signal_type, extractor_version) DO UPDATE SET
              signal_value=EXCLUDED.signal_value,
              score=EXCLUDED.score,
              confidence=EXCLUDED.confidence,
              evidence_json=EXCLUDED.evidence_json,
              generated_at=now()
            """,
            (
                candidate_id,
                signal["signal_type"],
                signal.get("signal_value"),
                signal.get("score"),
                signal.get("confidence"),
                json.dumps(signal.get("evidence", {}), ensure_ascii=False),
                extractor_version,
            ),
        )
    refresh_search_document(conn, candidate_id)
    refresh_embedding(conn, candidate_id)
    audit(conn, "candidate_enriched", "candidate_profile", candidate_id, {"extractor_version": extractor_version})
    conn.commit()
    return get_candidate_detail(conn, candidate_id)


def clear_enrichment(conn: Any, candidate_id: str, extractor_version: str) -> None:
    for table in ("work_experiences", "education_experiences", "projects", "skills", "candidate_signals"):
        conn.execute(f"DELETE FROM {table} WHERE candidate_id=%s AND extractor_version=%s", (candidate_id, extractor_version))
    conn.execute("DELETE FROM compensation_observations WHERE candidate_id=%s AND source_type IN ('profile', 'resume')", (candidate_id,))
    conn.execute("DELETE FROM candidate_preferences WHERE candidate_id=%s AND source_type='profile'", (candidate_id,))
    conn.execute("DELETE FROM candidate_sensitive_attributes WHERE candidate_id=%s AND source_type='resume'", (candidate_id,))


def write_evidence(
    conn: Any,
    candidate_id: str,
    resume_version_id: int | None,
    source_table: str,
    text: str | None,
    field_path: str,
    confidence: float,
) -> str | None:
    clean = re.sub(r"\s+", " ", str(text or "").strip())
    if not clean:
        return None
    evidence_id = "ev_" + hash_text(f"{candidate_id}|{resume_version_id}|{field_path}|{clean}")[:24]
    resume_text = ""
    if resume_version_id:
        row = conn.execute("SELECT resume_text FROM resume_versions WHERE resume_version_id=%s", (resume_version_id,)).fetchone()
        resume_text = row["resume_text"] if row else ""
    start = resume_text.find(clean) if resume_text else -1
    conn.execute(
        """
        INSERT INTO resume_evidence_spans (
          evidence_span_id, candidate_id, resume_version_id, source_table,
          field_path, text, start_char, end_char, confidence
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(evidence_span_id) DO NOTHING
        """,
        (evidence_id, candidate_id, resume_version_id, source_table, field_path, clean, start if start >= 0 else None, start + len(clean) if start >= 0 else None, confidence),
    )
    return evidence_id


def add_contact(
    conn: Any,
    candidate_id: str,
    contact_type: str,
    contact_value: str,
    *,
    source_type: str = "manual",
    consent_status: str = "unknown",
    visibility: str = "restricted",
    evidence_span_id: str | None = None,
    confidence: float = 0.9,
    commit: bool = True,
) -> dict[str, Any]:
    migrate(conn)
    if contact_type == "email" and not EMAIL_RE.fullmatch(contact_value.strip()):
        raise ValueError("invalid email")
    value = contact_value.strip()
    contact_hash = hash_text(normalize(value))
    conn.execute(
        """
        INSERT INTO candidate_contacts (
          candidate_id, contact_type, contact_value, contact_hash, source_type,
          consent_status, visibility, evidence_span_id, confidence
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(candidate_id, contact_type, contact_hash) DO UPDATE SET
          source_type=EXCLUDED.source_type,
          consent_status=EXCLUDED.consent_status,
          visibility=EXCLUDED.visibility,
          confidence=GREATEST(COALESCE(candidate_contacts.confidence, 0), EXCLUDED.confidence),
          updated_at=now()
        """,
        (candidate_id, contact_type, value, contact_hash, source_type, consent_status, visibility, evidence_span_id, confidence),
    )
    identifier_type = f"{contact_type}_hash"
    conn.execute(
        """
        INSERT INTO candidate_identifiers (
          candidate_id, identifier_type, identifier_hash, identifier_display, source_type, confidence
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(identifier_type, identifier_hash) DO UPDATE SET candidate_id=EXCLUDED.candidate_id, updated_at=now()
        """,
        (candidate_id, identifier_type, contact_hash, redact_contact(contact_type, value), source_type, confidence),
    )
    audit(conn, "candidate_contact_added", "candidate_profile", candidate_id, {"contact_type": contact_type})
    if commit:
        conn.commit()
    return {"status": "ready", "candidate_id": candidate_id, "contact_type": contact_type, "contact_display": redact_contact(contact_type, value)}


def get_candidate_profile(conn: Any, candidate_id: str) -> dict[str, Any] | None:
    migrate(conn)
    row = conn.execute("SELECT * FROM candidate_profiles WHERE candidate_id=%s", (candidate_id,)).fetchone()
    return row_to_dict(row) if row else None


def get_candidate_detail(conn: Any, candidate_id: str) -> dict[str, Any]:
    profile = get_candidate_profile(conn, candidate_id)
    if not profile:
        raise KeyError(f"candidate not found: {candidate_id}")
    detail = {"profile": profile}
    child_tables = {
        "identifiers": "candidate_identifiers",
        "contacts": "candidate_contacts",
        "resumes": "resume_versions",
        "work_experiences": "work_experiences",
        "education_experiences": "education_experiences",
        "projects": "projects",
        "skills": "skills",
        "compensation": "compensation_observations",
        "preferences": "candidate_preferences",
        "sensitive_attributes": "candidate_sensitive_attributes",
        "signals": "candidate_signals",
        "matches": "candidate_matches",
        "interactions": "candidate_interactions",
        "tasks": "candidate_tasks",
    }
    for key, table in child_tables.items():
        rows = conn.execute(f"SELECT * FROM {table} WHERE candidate_id=%s ORDER BY 1 DESC LIMIT 200", (candidate_id,)).fetchall()
        detail[key] = [row_to_dict(row) for row in rows]
    pools = conn.execute(
        """
        SELECT p.*, m.fit_score, m.reason, m.assigned_by, m.updated_at AS membership_updated_at
        FROM candidate_pool_memberships m
        JOIN talent_pools p ON p.pool_id=m.pool_id
        WHERE m.candidate_id=%s
        ORDER BY m.fit_score DESC NULLS LAST
        """,
        (candidate_id,),
    ).fetchall()
    detail["talent_pools"] = [row_to_dict(row) for row in pools]
    return detail


def latest_resume(conn: Any, candidate_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM resume_versions WHERE candidate_id=%s ORDER BY collected_at DESC NULLS LAST, resume_version_id DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def search_candidates(conn: Any, **filters: Any) -> dict[str, Any]:
    migrate(conn)
    where = ["1=1"]
    params: list[Any] = []
    joins = []
    order = "p.updated_at DESC"
    query = filters.get("query")
    if query:
        joins.append("JOIN talent_search_documents d ON d.candidate_id=p.candidate_id")
        where.append("d.search_vector @@ websearch_to_tsquery('simple', %s)")
        params.append(query)
        order = "ts_rank(d.search_vector, websearch_to_tsquery('simple', %s)) DESC"
        params.append(query)
    for column, value in (("city", filters.get("city")), ("education_level", filters.get("education")), ("highest_grade", filters.get("grade"))):
        if value:
            where.append(f"p.{column} ILIKE %s" if column != "highest_grade" else f"p.{column}=%s")
            params.append(f"%{value}%" if column != "highest_grade" else value)
    if filters.get("active_status"):
        where.append("p.active_status ILIKE %s")
        params.append(f"%{filters['active_status']}%")
    if filters.get("pool"):
        joins.append("JOIN candidate_pool_memberships pm ON pm.candidate_id=p.candidate_id JOIN talent_pools tp ON tp.pool_id=pm.pool_id")
        where.append("tp.name ILIKE %s")
        params.append(f"%{filters['pool']}%")
    limit = int(filters.get("limit") or 20)
    rows = conn.execute(
        f"""
        SELECT DISTINCT p.*
        FROM candidate_profiles p
        {' '.join(joins)}
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT %s
        """,
        tuple(params + [limit]),
    ).fetchall()
    return {"status": "ready", "count": len(rows), "candidates": [row_to_dict(row) for row in rows]}


def semantic_search(conn: Any, query: str, limit: int = 20) -> dict[str, Any]:
    migrate(conn)
    embedding = vector_literal(simple_embedding(query))
    rows = conn.execute(
        """
        SELECT p.*, 1 - (e.embedding <=> %s::vector) AS semantic_score
        FROM candidate_embeddings e
        JOIN candidate_profiles p ON p.candidate_id=e.candidate_id
        WHERE e.embedding_type='profile'
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
        """,
        (embedding, embedding, limit),
    ).fetchall()
    return {"status": "ready", "count": len(rows), "candidates": [row_to_dict(row) for row in rows]}


def match_job(conn: Any, job: dict[str, Any], limit: int = 20) -> dict[str, Any]:
    migrate(conn)
    rows = conn.execute("SELECT candidate_id FROM candidate_profiles").fetchall()
    matches = []
    for row in rows:
        detail = get_candidate_detail(conn, str(row["candidate_id"]))
        score, reasons, risks, evidence = score_job_match(detail, job)
        grade = grade_for_score(score)
        conn.execute(
            """
            INSERT INTO candidate_matches (
              candidate_id, job_id, job_title, job_description, score, grade,
              reasons_json, risks_json, evidence_json, matcher_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            """,
            (
                detail["profile"]["candidate_id"],
                job.get("job_id"),
                job.get("job_title") or job.get("title"),
                job.get("job_description") or job.get("description"),
                score,
                grade,
                json.dumps(reasons, ensure_ascii=False),
                json.dumps(risks, ensure_ascii=False),
                json.dumps(evidence, ensure_ascii=False),
                "talent_match_rules_v1",
            ),
        )
        matches.append({"candidate": detail["profile"], "score": score, "grade": grade, "reasons": reasons, "risks": risks, "evidence": evidence})
    conn.commit()
    matches.sort(key=lambda item: item["score"], reverse=True)
    return {"status": "ready", "count": min(len(matches), limit), "matches": matches[:limit]}


def auto_assign_pools(conn: Any, candidate_id: str | None = None) -> dict[str, Any]:
    migrate(conn)
    rows = conn.execute(
        "SELECT candidate_id FROM candidate_profiles WHERE %s IS NULL OR candidate_id=%s",
        (candidate_id, candidate_id),
    ).fetchall()
    assignments = []
    for row in rows:
        detail = get_candidate_detail(conn, str(row["candidate_id"]))
        pool_name, reason, fit_score = infer_pool(detail)
        if not pool_name:
            continue
        pool = conn.execute(
            """
            INSERT INTO talent_pools (name, description, rules_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT(name) DO UPDATE SET updated_at=now()
            RETURNING pool_id
            """,
            (pool_name, f"自动归类：{pool_name}", json.dumps({"source": "auto_assign_v1"}, ensure_ascii=False)),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO candidate_pool_memberships (candidate_id, pool_id, fit_score, reason)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(candidate_id, pool_id) DO UPDATE SET
              fit_score=EXCLUDED.fit_score,
              reason=EXCLUDED.reason,
              updated_at=now()
            """,
            (detail["profile"]["candidate_id"], pool["pool_id"], fit_score, reason),
        )
        assignments.append({"candidate_id": str(detail["profile"]["candidate_id"]), "pool_id": str(pool["pool_id"]), "pool_name": pool_name, "fit_score": fit_score, "reason": reason})
    conn.commit()
    return {"status": "ready", "count": len(assignments), "assignments": assignments}


def create_review_tasks(conn: Any, min_grade: str = "B", days_from_now: int = 30) -> dict[str, Any]:
    migrate(conn)
    rows = conn.execute("SELECT * FROM candidate_profiles WHERE highest_grade IN ('A','B')").fetchall()
    tasks = []
    for row in rows:
        profile = row_to_dict(row)
        if grade_rank(profile.get("highest_grade")) < grade_rank(min_grade):
            continue
        due_at = utc_now() + timedelta(days=days_from_now)
        existing = conn.execute(
            "SELECT task_id FROM candidate_tasks WHERE candidate_id=%s AND task_type='review' AND status='open'",
            (profile["candidate_id"],),
        ).fetchone()
        if existing:
            tasks.append({"task_id": str(existing["task_id"]), "candidate_id": str(profile["candidate_id"]), "status": "existing"})
            continue
        task = conn.execute(
            """
            INSERT INTO candidate_tasks (
              candidate_id, task_type, due_at, title, description, priority
            ) VALUES (%s, 'review', %s, %s, %s, %s)
            RETURNING task_id
            """,
            (
                profile["candidate_id"],
                due_at,
                f"复评候选人：{profile.get('display_name') or profile.get('masked_name') or profile['candidate_id']}",
                "B级以上候选人定期复评，检查新岗位匹配、活跃状态和联系窗口。",
                "high" if profile.get("highest_grade") == "A" else "medium",
            ),
        ).fetchone()
        tasks.append({"task_id": str(task["task_id"]), "candidate_id": str(profile["candidate_id"]), "due_at": due_at.isoformat()})
    conn.commit()
    return {"status": "ready", "count": len(tasks), "tasks": tasks}


def draft_email(conn: Any, candidate_id: str, job: dict[str, Any]) -> dict[str, Any]:
    migrate(conn)
    profile = get_candidate_profile(conn, candidate_id)
    if not profile:
        raise KeyError(f"candidate not found: {candidate_id}")
    contact = conn.execute(
        """
        SELECT * FROM candidate_contacts
        WHERE candidate_id=%s AND contact_type='email'
        ORDER BY verified_at DESC NULLS LAST, updated_at DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    if not contact:
        return {"status": "needs_contact", "message": "该候选人没有可用 email，不能生成自动联系草稿。"}
    job_title = job.get("job_title") or job.get("title") or profile.get("expected_position") or "这个岗位"
    company = job.get("company") or "我们团队"
    name = profile.get("display_name") or profile.get("masked_name") or "你好"
    subject = f"{job_title} 机会沟通"
    body = f"{name}，你好：\n\n我在简历库里看到你过往经历和 {job_title} 比较相关，想代表{company}和你简单沟通一下。如果你近期愿意看看新机会，方便回复这封邮件或告诉我一个适合沟通的时间吗？\n\n谢谢。"
    conn.execute(
        """
        INSERT INTO candidate_interactions (
          candidate_id, interaction_type, job_title, message_text, status, channel, raw_json
        ) VALUES (%s, 'email_draft', %s, %s, 'draft', 'email', %s::jsonb)
        """,
        (candidate_id, job_title, body, json.dumps({"subject": subject, "to": redact_contact("email", contact["contact_value"])}, ensure_ascii=False)),
    )
    conn.commit()
    return {"status": "draft", "candidate_id": candidate_id, "to": redact_contact("email", contact["contact_value"]), "subject": subject, "body": body}


def refresh_search_document(conn: Any, candidate_id: str) -> None:
    profile = get_candidate_profile(conn, candidate_id)
    if not profile:
        return
    parts = [
        profile.get("display_name"),
        profile.get("masked_name"),
        profile.get("current_title"),
        profile.get("current_company"),
        profile.get("school"),
        profile.get("major"),
        profile.get("expected_position"),
        profile.get("profile_summary"),
    ]
    for table, column in (
        ("resume_versions", "resume_text"),
        ("work_experiences", "description"),
        ("education_experiences", "school"),
        ("projects", "technical_context"),
        ("skills", "skill_name"),
        ("candidate_signals", "signal_value"),
    ):
        rows = conn.execute(f"SELECT {column} FROM {table} WHERE candidate_id=%s", (candidate_id,)).fetchall()
        parts.extend(row[column] for row in rows if row.get(column))
    content = "\n".join(str(part) for part in parts if part)
    tags = " ".join(profile.get("tags_json") or [])
    conn.execute(
        """
        INSERT INTO talent_search_documents (candidate_id, content, tags, search_vector)
        VALUES (%s, %s, %s, to_tsvector('simple', %s || ' ' || %s))
        ON CONFLICT(candidate_id) DO UPDATE SET
          content=EXCLUDED.content,
          tags=EXCLUDED.tags,
          search_vector=EXCLUDED.search_vector,
          updated_at=now()
        """,
        (candidate_id, content, tags, content, tags),
    )


def refresh_embedding(conn: Any, candidate_id: str) -> None:
    row = conn.execute("SELECT content FROM talent_search_documents WHERE candidate_id=%s", (candidate_id,)).fetchone()
    if not row or not row["content"]:
        return
    content = row["content"]
    conn.execute(
        "DELETE FROM candidate_embeddings WHERE candidate_id=%s AND embedding_type='profile' AND embedding_model=%s",
        (candidate_id, EMBEDDING_MODEL),
    )
    conn.execute(
        """
        INSERT INTO candidate_embeddings (
          candidate_id, embedding_type, embedding_model, embedding, source_text_hash
        ) VALUES (%s, 'profile', %s, %s::vector, %s)
        ON CONFLICT(candidate_id, embedding_type, embedding_model, source_text_hash) DO NOTHING
        """,
        (candidate_id, EMBEDDING_MODEL, vector_literal(simple_embedding(content)), hash_text(content)),
    )


def extract_contacts(text: str) -> list[dict[str, str]]:
    contacts = []
    for match in EMAIL_RE.finditer(text or ""):
        contacts.append({"contact_type": "email", "contact_value": match.group(0), "evidence_text": match.group(0)})
    for match in PHONE_RE.finditer(text or ""):
        contacts.append({"contact_type": "phone", "contact_value": match.group(0), "evidence_text": match.group(0)})
    for match in WECHAT_RE.finditer(text or ""):
        contacts.append({"contact_type": "wechat", "contact_value": match.group(1), "evidence_text": match.group(0)})
    return contacts


def extract_work_experiences(profile: dict[str, Any], resume: dict[str, Any] | None) -> list[dict[str, Any]]:
    companies = list(profile.get("source_summary_json", {}).get("detail_companies_json", []) or [])
    if resume:
        companies.extend(resume.get("detail_companies_json") or [])
    if not companies and profile.get("current_company"):
        companies.append(profile["current_company"])
    items = []
    for line in unique_strings(companies):
        parts = [part.strip() for part in re.split(r"[|｜]", line) if part.strip()]
        date_range = DATE_RANGE_RE.search(line)
        start = normalize_date(date_range.group("start")) if date_range else None
        end = normalize_date(date_range.group("end")) if date_range else None
        items.append(
            {
                "company_name": parts[0] if parts else line,
                "title": parts[1] if len(parts) > 1 else profile.get("current_title"),
                "start_date": start,
                "end_date": end,
                "duration_months": months_between(start, end) if start else None,
                "description": line,
                "tech_stack": extract_skill_terms(line),
                "achievements": extract_achievements(line),
                "evidence_text": line,
                "confidence": 0.62,
            }
        )
    return items[:30]


def extract_education(profile: dict[str, Any], resume: dict[str, Any] | None) -> list[dict[str, Any]]:
    schools = [profile.get("school")]
    if resume:
        schools.extend(resume.get("detail_schools_json") or [])
    items = []
    for line in unique_strings([item for item in schools if item]):
        parts = [part.strip() for part in re.split(r"[|｜·]", line) if part.strip()]
        degree = next((level for level in ("博士", "硕士", "本科", "大专", "高中", "中专") if level in line), profile.get("education_level"))
        tags = [tag for tag in ("985", "211", "双一流", "QS", "TOP") if tag.lower() in line.lower()]
        items.append({"school": parts[0], "major": parts[1] if len(parts) > 1 else profile.get("major"), "degree": degree, "ranking_tags": tags, "evidence_text": line, "confidence": 0.72})
    return items[:10]


def extract_projects(text: str) -> list[dict[str, Any]]:
    items = []
    capture = False
    for line in [line.strip() for line in (text or "").splitlines() if line.strip()]:
        if "项目经历" in line or "项目经验" in line:
            capture = True
            continue
        if capture and re.search(r"教育经历|工作经历|期望职位|个人优势", line):
            break
        if capture and len(line) >= 8:
            items.append({"project_name": line[:60], "technical_context": line, "outcomes": extract_achievements(line), "evidence_text": line, "confidence": 0.55})
    return items[:12]


def extract_sensitive_attributes(text: str) -> list[dict[str, Any]]:
    items = []
    for pattern, attr_type in ((r"已婚|未婚|结婚|婚育", "marital_or_family"), (r"孩子|育有|宝妈|宝爸", "family"), (r"健康|病史", "health")):
        for match in re.finditer(pattern, text or ""):
            items.append({"attribute_type": attr_type, "attribute_value": match.group(0), "evidence_text": match.group(0), "confidence": 0.55})
    return items


def extract_preferences(profile: dict[str, Any]) -> list[tuple[str, str]]:
    pairs = []
    for key, pref_type in (("city", "city"), ("expected_position", "position"), ("expected_salary_text", "salary"), ("job_status", "job_status")):
        if profile.get(key):
            pairs.append((pref_type, str(profile[key])))
    return pairs


def extract_skill_terms(text: str | None) -> list[str]:
    common = ["Java", "Python", "Go", "Golang", "React", "Vue", "Node.js", "SpringBoot", "Spring Cloud", "MySQL", "Redis", "Kafka", "Docker", "Kubernetes", "K8s", "LLM", "RAG", "Agent", "大模型", "机器学习", "深度学习", "数据分析", "HRBP", "招聘", "组织发展", "市场营销", "产品", "运营", "算法", "测试"]
    lowered = (text or "").lower()
    return unique_strings(skill for skill in common if skill.lower() in lowered)


def extract_salary_mentions(text: str) -> list[str]:
    return unique_strings(match.group(0) for match in SALARY_RE.finditer(text or ""))


def extract_achievements(text: str) -> list[str]:
    return re.findall(r"(?:提升|增长|降低|完成|负责|主导|搭建|优化)[^。；;]{4,80}", text or "")[:8]


def write_compensation(conn: Any, candidate_id: str, observation_type: str, salary_text: str | None, evidence_span_id: str | None, source_type: str, confidence: float) -> None:
    salary = parse_salary(salary_text)
    if not salary:
        return
    conn.execute(
        """
        INSERT INTO compensation_observations (
          candidate_id, observation_type, salary_text, monthly_min_k, monthly_max_k,
          months, annual_min_k, annual_max_k, evidence_span_id, confidence, source_type
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (candidate_id, observation_type, salary_text, salary["min_k"], salary["max_k"], salary["months"], salary["annual_min_k"], salary["annual_max_k"], evidence_span_id, confidence, source_type),
    )


def generate_signals(conn: Any, candidate_id: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    work_rows = conn.execute("SELECT * FROM work_experiences WHERE candidate_id=%s", (candidate_id,)).fetchall()
    skill_rows = conn.execute("SELECT * FROM skills WHERE candidate_id=%s", (candidate_id,)).fetchall()
    comp_rows = conn.execute("SELECT * FROM compensation_observations WHERE candidate_id=%s", (candidate_id,)).fetchall()
    avg_months = None
    if work_rows:
        durations = [int(row["duration_months"]) for row in work_rows if row.get("duration_months")]
        avg_months = sum(durations) / len(durations) if durations else None
    years = float(profile["work_years_value"]) if profile.get("work_years_value") is not None else None
    signals = [
        {"signal_type": "tenure_stability", "signal_value": "stable" if avg_months and avg_months >= 24 else "frequent_moves" if avg_months else "uncertain", "score": min(100, round((avg_months or 12) / 36 * 100, 1)), "confidence": 0.65 if work_rows else 0.35, "evidence": {"avg_duration_months": avg_months}},
        {"signal_type": "skill_depth", "signal_value": "broad" if len(skill_rows) >= 8 else "focused" if len(skill_rows) >= 3 else "limited", "score": min(100, len(skill_rows) * 10), "confidence": 0.7 if skill_rows else 0.3, "evidence": {"skill_count": len(skill_rows)}},
        {"signal_type": "seniority_signal", "signal_value": "senior" if (years or 0) >= 8 else "mid" if (years or 0) >= 3 else "junior_or_unknown", "score": min(100, int((years or 0) * 10)), "confidence": 0.7 if years else 0.3, "evidence": {"work_years_value": years}},
        {"signal_type": "mobility_signal", "signal_value": mobility_label(profile.get("job_status"), profile.get("active_status")), "score": mobility_score(profile.get("job_status"), profile.get("active_status")), "confidence": 0.65, "evidence": {"job_status": profile.get("job_status"), "active_status": profile.get("active_status")}},
        {"signal_type": "compensation_pressure", "signal_value": compensation_pressure(comp_rows), "score": compensation_pressure_score(comp_rows), "confidence": 0.65 if comp_rows else 0.25, "evidence": {"compensation_observations": len(comp_rows)}},
        {"signal_type": "contact_readiness", "signal_value": "email_available" if has_email(conn, candidate_id) else "no_email", "score": 85 if has_email(conn, candidate_id) else 20, "confidence": 0.9, "evidence": {"email_available": has_email(conn, candidate_id)}},
    ]
    salary_growth = salary_growth_signal(comp_rows)
    if salary_growth:
        signals.append(salary_growth)
    return signals


def score_job_match(detail: dict[str, Any], job: dict[str, Any]) -> tuple[int, list[str], list[str], dict[str, Any]]:
    profile = detail["profile"]
    text = " ".join([str(profile.get("profile_summary") or ""), str(profile.get("expected_position") or ""), " ".join(skill.get("skill_name", "") for skill in detail.get("skills", [])), " ".join(exp.get("description", "") or "" for exp in detail.get("work_experiences", []))]).lower()
    keywords = normalize_keywords(job)
    matched = [keyword for keyword in keywords if keyword.lower() in text]
    score = 25
    reasons = []
    risks = []
    if keywords:
        score += round(40 * len(matched) / len(keywords))
        reasons.append("匹配关键词：" + "、".join(matched[:8])) if matched else risks.append("未命中岗位关键词")
    min_years = parse_years(job.get("min_years") or job.get("minimum_years"))
    years = float(profile["work_years_value"]) if profile.get("work_years_value") is not None else None
    if min_years is not None:
        if years is not None and years >= min_years:
            score += 15
            reasons.append(f"工作年限 {years:g} 年达到要求")
        else:
            risks.append("工作年限不足或无法确认")
    if job.get("education") and profile.get("education_level"):
        if education_rank(profile["education_level"]) >= education_rank(job["education"]):
            score += 10
            reasons.append("学历满足要求")
        else:
            risks.append("学历低于要求")
    if job.get("city") and profile.get("city") and str(job["city"]) in str(profile["city"]):
        score += 5
        reasons.append("城市偏好匹配")
    score = max(0, min(100, int(score)))
    return score, reasons or ["信息有限，建议人工复核"], risks, {"matched_keywords": matched, "candidate_id": str(profile["candidate_id"])}


def infer_pool(detail: dict[str, Any]) -> tuple[str | None, str, float]:
    profile = detail["profile"]
    text = " ".join([str(profile.get("expected_position") or ""), str(profile.get("profile_summary") or "")] + [skill.get("skill_name", "") for skill in detail.get("skills", [])]).lower()
    if any(key in text for key in ("java", "spring", "后端", "golang", "go")):
        return "后端工程师池", "命中后端/Java/Go 技能或岗位", 0.82
    if any(key in text for key in ("算法", "机器学习", "大模型", "llm", "rag", "agent")):
        return "AI工程师池", "命中 AI/算法/大模型 信号", 0.84
    if any(key in text for key in ("hrbp", "招聘", "组织")):
        return "HR与招聘池", "命中 HR/招聘 信号", 0.8
    if profile.get("expected_position"):
        return f"{profile['expected_position']}人才池", "按期望岗位归池", 0.55
    return None, "", 0


def simple_embedding(text: str, dims: int = EMBEDDING_DIMS) -> list[float]:
    vector = [0.0] * dims
    for token in re.findall(r"[\w\u4e00-\u9fa5]{2,}", (text or "").lower()):
        vector[int(hash_text(token)[:8], 16) % dims] += 1.0
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / norm for item in vector]


def parse_salary(value: Any) -> dict[str, int] | None:
    match = SALARY_RE.search(str(value or ""))
    if not match:
        return None
    min_k = int(match.group("min"))
    max_k = int(match.group("max") or match.group("min"))
    months = int(match.group("months") or 12)
    return {"min_k": min_k, "max_k": max_k, "months": months, "annual_min_k": min_k * months, "annual_max_k": max_k * months}


def parse_years(value: Any) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
    return float(match.group(1)) if match else None


def normalize_date(value: str | None) -> date | None:
    if not value or value in {"至今", "现在"}:
        return None
    text = value.replace(".", "-").replace("/", "-")
    if re.fullmatch(r"20\d{2}", text):
        return date(int(text), 1, 1)
    match = re.fullmatch(r"(20\d{2})-(\d{1,2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), 1)
    return None


def months_between(start: date | None, end: date | None) -> int | None:
    if not start:
        return None
    end = end or utc_now().date()
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def education_rank(value: Any) -> int:
    ranks = {"高中": 1, "中专": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5}
    return max((rank for name, rank in ranks.items() if name in str(value or "")), default=0)


def grade_rank(value: Any) -> int:
    return {"D": 1, "C": 2, "B": 3, "A": 4}.get(str(value or "").upper(), 0)


def grade_for_score(score: int) -> str:
    return "A" if score >= 75 else "B" if score >= 55 else "C" if score >= 35 else "D"


def unique_strings(items: Any) -> list[str]:
    result = []
    seen = set()
    for item in items or []:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if text and text.lower() not in seen:
            result.append(text)
            seen.add(text.lower())
    return result


def first_item(value: Any) -> str | None:
    items = json_loads(value, []) if not isinstance(value, list) else value
    return str(items[0]) if items else None


def infer_skill_type(skill: str) -> str:
    lowered = skill.lower()
    if lowered in {"java", "python", "go", "golang", "javascript", "typescript"}:
        return "programming_language"
    if lowered in {"react", "vue", "springboot", "spring cloud", "node.js"}:
        return "framework"
    if lowered in {"mysql", "redis", "kafka"}:
        return "infrastructure"
    if any(key in lowered for key in ("招聘", "hrbp", "组织")):
        return "hr"
    return "skill"


def mobility_label(job_status: Any, active_status: Any) -> str:
    text = f"{job_status or ''} {active_status or ''}"
    if "随时到岗" in text or "月内到岗" in text:
        return "high_mobility"
    if "考虑机会" in text or "刚刚活跃" in text:
        return "open_to_opportunities"
    if "暂不考虑" in text:
        return "low_mobility"
    return "unknown"


def mobility_score(job_status: Any, active_status: Any) -> int:
    return {"high_mobility": 85, "open_to_opportunities": 70, "low_mobility": 25, "unknown": 40}[mobility_label(job_status, active_status)]


def compensation_pressure(comp_rows: list[dict[str, Any]]) -> str:
    if not comp_rows:
        return "unknown"
    highest = max(int(row.get("annual_max_k") or 0) for row in comp_rows)
    return "very_high" if highest >= 800 else "high" if highest >= 500 else "medium" if highest >= 300 else "low"


def compensation_pressure_score(comp_rows: list[dict[str, Any]]) -> int:
    return {"very_high": 90, "high": 75, "medium": 55, "low": 35, "unknown": 20}[compensation_pressure(comp_rows)]


def salary_growth_signal(comp_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    annuals = [int(row.get("annual_max_k") or 0) for row in comp_rows if row.get("annual_max_k")]
    if len(annuals) < 2:
        return None
    growth = max(annuals) - min(annuals)
    return {"signal_type": "salary_growth_velocity", "signal_value": "fast_growth" if growth >= 200 else "moderate_growth", "score": min(100, growth / 3), "confidence": 0.45, "evidence": {"annual_salary_values_k": annuals, "growth_k": growth}}


def has_email(conn: Any, candidate_id: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM candidate_contacts WHERE candidate_id=%s AND contact_type='email' LIMIT 1", (candidate_id,)).fetchone())


def normalize_keywords(job: dict[str, Any]) -> list[str]:
    value = job.get("required_keywords") or job.get("keywords") or []
    if isinstance(value, str):
        value = re.split(r"[,，/、\s]+", value)
    keywords = [str(item).strip() for item in value if str(item).strip()]
    title = str(job.get("job_title") or job.get("title") or "").strip()
    if title:
        keywords.extend(item for item in re.split(r"[,，/、\s_\\-]+", title) if len(item) >= 2)
    return unique_strings(keywords)


def safe_display_identifier(identifier_type: str, value: str) -> str | None:
    if "email" in identifier_type:
        return redact_contact("email", value)
    if "phone" in identifier_type:
        return redact_contact("phone", value)
    if identifier_type.endswith("hash"):
        return None
    return str(value)[:64]


def redact_contact(contact_type: str, value: str) -> str:
    if contact_type == "email" and "@" in value:
        name, domain = value.split("@", 1)
        return name[:2] + "***@" + domain
    if contact_type == "phone" and len(value) >= 7:
        return value[:3] + "****" + value[-4:]
    return value[:2] + "***" if len(value) > 2 else "***"


def audit(conn: Any, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_events (event_type, entity_type, entity_id, event_json) VALUES (%s, %s, %s, %s::jsonb)",
        (event_type, entity_type, str(entity_id), json.dumps(payload, ensure_ascii=False)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Postgres smart talent library")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    ingest = sub.add_parser("ingest-boss")
    ingest.add_argument("--sqlite-db", default="data-python/boss_talent.sqlite")
    ingest.add_argument("--scan-run-id")
    ingest.add_argument("--source-fingerprint")
    ingest.add_argument("--limit", type=int)
    enrich = sub.add_parser("enrich")
    enrich.add_argument("candidate_id")
    args = parser.parse_args()
    with connect(args.database_url) as conn:
        if args.command == "migrate":
            migrate(conn)
            result = {"status": "ready", "message": "schema migrated"}
        elif args.command == "ingest-boss":
            result = ingest_boss_snapshot_from_sqlite(
                conn,
                Path(args.sqlite_db),
                scan_run_id=args.scan_run_id,
                source_fingerprint=args.source_fingerprint,
                limit=args.limit,
            )
        else:
            result = enrich_candidate(conn, args.candidate_id)
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
