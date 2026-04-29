from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def main() -> None:
    args = parse_args()
    run_path = Path(args.run_file).resolve()
    db_path = Path(args.db).resolve()
    payload = json.loads(run_path.read_text(encoding="utf-8"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        create_schema(conn)
        import_candidates(conn, payload.get("candidates", []))
        import_observations(conn, payload.get("observations", []))
        import_resume_snapshots(conn, payload.get("resume_snapshots", []))
        import_job_postings(conn, payload.get("job_postings", []))
        conn.commit()

    print(f"SQLite database: {db_path}")
    print(f"candidates: {count_rows(db_path, 'candidates')}")
    print(f"candidate_observations: {count_rows(db_path, 'candidate_observations')}")
    print(f"candidate_resume_snapshots: {count_rows(db_path, 'candidate_resume_snapshots')}")
    print(f"boss_job_postings: {count_rows(db_path, 'boss_job_postings')}")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS candidates (
          source_fingerprint TEXT PRIMARY KEY,
          source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
          masked_name TEXT,
          age INTEGER,
          gender TEXT,
          years_experience TEXT,
          education_level TEXT,
          school TEXT,
          major TEXT,
          expected_city TEXT,
          expected_position TEXT,
          expected_salary TEXT,
          job_status TEXT,
          active_status TEXT,
          short_summary TEXT,
          tags_json TEXT NOT NULL DEFAULT '[]',
          source_url TEXT,
          last_seen_at TEXT,
          detail_summary TEXT,
          detail_tags_json TEXT NOT NULL DEFAULT '[]',
          detail_schools_json TEXT NOT NULL DEFAULT '[]',
          detail_companies_json TEXT NOT NULL DEFAULT '[]',
          detail_positions_json TEXT NOT NULL DEFAULT '[]',
          parsed_confidence REAL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS candidate_observations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
          source_fingerprint TEXT NOT NULL,
          observed_at TEXT,
          source_url TEXT,
          search_keyword TEXT,
          search_city TEXT,
          search_filters_json TEXT NOT NULL DEFAULT '[]',
          visible_card_json TEXT NOT NULL DEFAULT '{}',
          parsed_confidence REAL
        );

        CREATE TABLE IF NOT EXISTS candidate_resume_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
          source_fingerprint TEXT NOT NULL,
          collected_at TEXT,
          source_url TEXT,
          parser_version TEXT NOT NULL DEFAULT 'resume_ocr_v1',
          resume_text TEXT NOT NULL,
          resume_text_hash TEXT NOT NULL,
          resume_sections_json TEXT NOT NULL DEFAULT '{}',
          detail_summary TEXT,
          detail_tags_json TEXT NOT NULL DEFAULT '[]',
          detail_schools_json TEXT NOT NULL DEFAULT '[]',
          detail_companies_json TEXT NOT NULL DEFAULT '[]',
          detail_positions_json TEXT NOT NULL DEFAULT '[]',
          ocr_engine TEXT,
          ocr_pages_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(source_fingerprint, resume_text_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_candidates_expected_position ON candidates(expected_position);
        CREATE INDEX IF NOT EXISTS idx_candidates_expected_city ON candidates(expected_city);
        CREATE INDEX IF NOT EXISTS idx_candidates_last_seen_at ON candidates(last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_observations_fingerprint ON candidate_observations(source_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_resume_snapshots_fingerprint ON candidate_resume_snapshots(source_fingerprint);

        CREATE TABLE IF NOT EXISTS boss_job_postings (
          source_fingerprint TEXT PRIMARY KEY,
          source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
          source_url TEXT,
          search_keyword TEXT,
          search_city TEXT,
          job_title TEXT,
          company_name TEXT,
          job_city TEXT,
          salary_text TEXT,
          experience_requirement TEXT,
          education_requirement TEXT,
          recruiter_name TEXT,
          recruiter_title TEXT,
          tags_json TEXT NOT NULL DEFAULT '[]',
          description TEXT,
          raw_card_json TEXT NOT NULL DEFAULT '{}',
          collected_at TEXT,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_boss_job_postings_company ON boss_job_postings(company_name);
        CREATE INDEX IF NOT EXISTS idx_boss_job_postings_title ON boss_job_postings(job_title);
        CREATE INDEX IF NOT EXISTS idx_boss_job_postings_city ON boss_job_postings(job_city);
        CREATE INDEX IF NOT EXISTS idx_boss_job_postings_collected_at ON boss_job_postings(collected_at);

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

        CREATE INDEX IF NOT EXISTS idx_org_intel_reports_company ON org_intel_reports(company_name);
        CREATE INDEX IF NOT EXISTS idx_org_intel_reports_generated_at ON org_intel_reports(generated_at);

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

        CREATE INDEX IF NOT EXISTS idx_org_findings_company ON org_findings(company_name);
        CREATE INDEX IF NOT EXISTS idx_org_findings_type ON org_findings(finding_type);
        CREATE INDEX IF NOT EXISTS idx_org_findings_generated_at ON org_findings(generated_at);

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
        """
    )


def import_candidates(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        conn.execute(
            """
            INSERT INTO candidates (
              source_fingerprint, source_platform, masked_name, age, gender, years_experience,
              education_level, school, major, expected_city, expected_position, expected_salary,
              job_status, active_status, short_summary, tags_json, source_url, last_seen_at,
              detail_summary, detail_tags_json, detail_schools_json, detail_companies_json,
              detail_positions_json, parsed_confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_fingerprint) DO UPDATE SET
              source_platform=excluded.source_platform,
              masked_name=excluded.masked_name,
              age=excluded.age,
              gender=excluded.gender,
              years_experience=excluded.years_experience,
              education_level=excluded.education_level,
              school=excluded.school,
              major=excluded.major,
              expected_city=excluded.expected_city,
              expected_position=excluded.expected_position,
              expected_salary=excluded.expected_salary,
              job_status=excluded.job_status,
              active_status=excluded.active_status,
              short_summary=excluded.short_summary,
              tags_json=excluded.tags_json,
              source_url=excluded.source_url,
              last_seen_at=excluded.last_seen_at,
              detail_summary=excluded.detail_summary,
              detail_tags_json=excluded.detail_tags_json,
              detail_schools_json=excluded.detail_schools_json,
              detail_companies_json=excluded.detail_companies_json,
              detail_positions_json=excluded.detail_positions_json,
              parsed_confidence=excluded.parsed_confidence,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                candidate.get("source_fingerprint"),
                candidate.get("source_platform", "boss_zhipin"),
                candidate.get("masked_name"),
                candidate.get("age"),
                candidate.get("gender"),
                candidate.get("years_experience"),
                candidate.get("education_level"),
                candidate.get("school"),
                candidate.get("major"),
                candidate.get("expected_city"),
                candidate.get("expected_position"),
                candidate.get("expected_salary"),
                candidate.get("job_status"),
                candidate.get("active_status"),
                candidate.get("short_summary"),
                as_json(candidate.get("tags_json", [])),
                candidate.get("source_url"),
                candidate.get("last_seen_at"),
                candidate.get("detail_summary"),
                as_json(candidate.get("detail_tags_json", [])),
                as_json(candidate.get("detail_schools_json", [])),
                as_json(candidate.get("detail_companies_json", [])),
                as_json(candidate.get("detail_positions_json", [])),
                candidate.get("parsed_confidence"),
            ),
        )


def import_observations(conn: sqlite3.Connection, observations: list[dict[str, Any]]) -> None:
    for observation in observations:
        conn.execute(
            """
            INSERT INTO candidate_observations (
              source_platform, source_fingerprint, observed_at, source_url, search_keyword,
              search_city, search_filters_json, visible_card_json, parsed_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.get("source_platform", "boss_zhipin"),
                observation.get("source_fingerprint"),
                observation.get("observed_at"),
                observation.get("source_url"),
                observation.get("search_keyword"),
                observation.get("search_city"),
                as_json(observation.get("search_filters_json", [])),
                as_json(observation.get("visible_card_json", {})),
                observation.get("parsed_confidence"),
            ),
        )


def import_resume_snapshots(conn: sqlite3.Connection, snapshots: list[dict[str, Any]]) -> None:
    for snapshot in snapshots:
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
                snapshot.get("source_fingerprint"),
                snapshot.get("collected_at"),
                snapshot.get("source_url"),
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


def import_job_postings(conn: sqlite3.Connection, postings: list[dict[str, Any]]) -> None:
    for posting in postings:
        conn.execute(
            """
            INSERT INTO boss_job_postings (
              source_fingerprint, source_platform, source_url, search_keyword, search_city,
              job_title, company_name, job_city, salary_text, experience_requirement,
              education_requirement, recruiter_name, recruiter_title, tags_json, description,
              raw_card_json, collected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_fingerprint) DO UPDATE SET
              source_platform=excluded.source_platform,
              source_url=excluded.source_url,
              search_keyword=excluded.search_keyword,
              search_city=excluded.search_city,
              job_title=excluded.job_title,
              company_name=excluded.company_name,
              job_city=excluded.job_city,
              salary_text=excluded.salary_text,
              experience_requirement=excluded.experience_requirement,
              education_requirement=excluded.education_requirement,
              recruiter_name=excluded.recruiter_name,
              recruiter_title=excluded.recruiter_title,
              tags_json=excluded.tags_json,
              description=excluded.description,
              raw_card_json=excluded.raw_card_json,
              collected_at=excluded.collected_at,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                posting.get("source_fingerprint"),
                posting.get("source_platform", "boss_zhipin"),
                posting.get("source_url"),
                posting.get("search_keyword"),
                posting.get("search_city"),
                posting.get("job_title"),
                posting.get("company_name"),
                posting.get("job_city"),
                posting.get("salary_text"),
                posting.get("experience_requirement"),
                posting.get("education_requirement"),
                posting.get("recruiter_name"),
                posting.get("recruiter_title"),
                as_json(posting.get("tags_json", [])),
                posting.get("description"),
                as_json(posting.get("raw_card_json", {})),
                posting.get("collected_at"),
            ),
        )


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def count_rows(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a BOSS capture run JSON into local SQLite.")
    parser.add_argument("run_file", help="data-python/runs/run-*.json")
    parser.add_argument("--db", default="data-python/boss_talent.sqlite", help="SQLite database path")
    return parser.parse_args()


if __name__ == "__main__":
    main()
