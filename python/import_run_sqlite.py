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
        conn.commit()

    print(f"SQLite database: {db_path}")
    print(f"candidates: {count_rows(db_path, 'candidates')}")
    print(f"candidate_observations: {count_rows(db_path, 'candidate_observations')}")
    print(f"candidate_resume_snapshots: {count_rows(db_path, 'candidate_resume_snapshots')}")


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
