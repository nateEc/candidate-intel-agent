from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import talent_library


DEFAULT_SQLITE_SOURCE_DB = Path(os.environ.get("BOSS_TALENT_DB", "data-python/boss_talent.sqlite")).resolve()

app = FastAPI(title="Smart Talent Library", version="1.0.0")


class BossSnapshotIngestRequest(BaseModel):
    sqlite_db: str | None = None
    scan_run_id: str | None = None
    source_fingerprint: str | None = None
    limit: int | None = Field(default=None, ge=1, le=10000)


class ContactRequest(BaseModel):
    contact_type: str = Field(pattern="^(email|phone|wechat)$")
    contact_value: str = Field(min_length=3, max_length=240)
    source_type: str = Field(default="manual", max_length=80)
    consent_status: str = Field(default="unknown", max_length=80)
    visibility: str = Field(default="restricted", max_length=80)


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=20, ge=1, le=200)


class MatchJobRequest(BaseModel):
    job_id: str | None = None
    job_title: str = Field(min_length=1, max_length=200)
    job_description: str | None = Field(default=None, max_length=10000)
    required_keywords: list[str] = Field(default_factory=list)
    min_years: int | None = Field(default=None, ge=0, le=80)
    education: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=20, ge=1, le=200)


class AutoAssignPoolsRequest(BaseModel):
    candidate_id: str | None = None


class ReviewTasksRequest(BaseModel):
    min_grade: str = Field(default="B", pattern="^[ABCD]$")
    days_from_now: int = Field(default=30, ge=1, le=365)


class EmailDraftRequest(BaseModel):
    candidate_id: str
    job_title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    job_description: str | None = Field(default=None, max_length=10000)


def connect():
    return talent_library.connect()


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        with connect() as conn:
            talent_library.migrate(conn)
            row = conn.execute("SELECT COUNT(*) AS count FROM candidate_profiles").fetchone()
        return {
            "ok": True,
            "service": "smart-talent-library",
            "database": "postgres",
            "pgvector": True,
            "candidate_profiles": int(row["count"]),
        }
    except Exception as exc:
        return {
            "ok": False,
            "service": "smart-talent-library",
            "database": "postgres",
            "message": str(exc),
        }


@app.post("/v1/talent/ingest/boss-snapshot")
def ingest_boss_snapshot(payload: BossSnapshotIngestRequest) -> dict[str, Any]:
    sqlite_db = Path(payload.sqlite_db).expanduser().resolve() if payload.sqlite_db else DEFAULT_SQLITE_SOURCE_DB
    with connect() as conn:
        return talent_library.ingest_boss_snapshot_from_sqlite(
            conn,
            sqlite_db,
            scan_run_id=payload.scan_run_id,
            source_fingerprint=payload.source_fingerprint,
            limit=payload.limit,
        )


@app.post("/v1/talent/candidates/{candidate_id}/enrich")
def enrich_candidate(candidate_id: str) -> dict[str, Any]:
    with connect() as conn:
        try:
            return talent_library.enrich_candidate(conn, candidate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/talent/candidates/{candidate_id}")
def get_candidate(candidate_id: str) -> dict[str, Any]:
    with connect() as conn:
        try:
            return talent_library.get_candidate_detail(conn, candidate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/talent/candidates/{candidate_id}/contacts")
def add_contact(candidate_id: str, payload: ContactRequest) -> dict[str, Any]:
    with connect() as conn:
        try:
            return talent_library.add_contact(
                conn,
                candidate_id,
                payload.contact_type,
                payload.contact_value,
                source_type=payload.source_type,
                consent_status=payload.consent_status,
                visibility=payload.visibility,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/talent/search")
def search_candidates(
    query: str | None = Query(default=None, max_length=1000),
    city: str | None = Query(default=None, max_length=80),
    education: str | None = Query(default=None, max_length=40),
    grade: str | None = Query(default=None, pattern="^[ABCD]$"),
    pool: str | None = Query(default=None, max_length=120),
    active_status: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    with connect() as conn:
        return talent_library.search_candidates(
            conn,
            query=query,
            city=city,
            education=education,
            grade=grade,
            pool=pool,
            active_status=active_status,
            limit=limit,
        )


@app.post("/v1/talent/semantic-search")
def semantic_search(payload: SemanticSearchRequest) -> dict[str, Any]:
    with connect() as conn:
        return talent_library.semantic_search(conn, payload.query, payload.limit)


@app.post("/v1/talent/match-job")
def match_job(payload: MatchJobRequest) -> dict[str, Any]:
    data = payload.model_dump()
    limit = data.pop("limit")
    with connect() as conn:
        return talent_library.match_job(conn, data, limit=limit)


@app.post("/v1/talent/pools/auto-assign")
def auto_assign_pools(payload: AutoAssignPoolsRequest) -> dict[str, Any]:
    with connect() as conn:
        return talent_library.auto_assign_pools(conn, payload.candidate_id)


@app.post("/v1/talent/tasks/review")
def create_review_tasks(payload: ReviewTasksRequest) -> dict[str, Any]:
    with connect() as conn:
        return talent_library.create_review_tasks(conn, payload.min_grade, payload.days_from_now)


@app.post("/v1/talent/outreach/email-draft")
def email_draft(payload: EmailDraftRequest) -> dict[str, Any]:
    with connect() as conn:
        try:
            return talent_library.draft_email(conn, payload.candidate_id, payload.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
