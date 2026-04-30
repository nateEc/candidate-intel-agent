from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import org_job_store as store
from org_intel import normalize_aliases
from org_intel_agent import should_refresh_source


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ.get("ORG_INTEL_DB", "data-python/boss_talent.sqlite")).resolve()
DEFAULT_OUTPUT_DIR = os.environ.get("ORG_INTEL_OUTPUT_DIR", "org-intel")
POLL_SECONDS = float(os.environ.get("ORG_INTEL_WORKER_POLL_SECONDS", "2"))
DEFAULT_CANDIDATES_CDP_URL = os.environ.get("BOSS_CANDIDATES_CDP_URL", "http://127.0.0.1:9222")
DEFAULT_JOBS_CDP_URL = os.environ.get("BOSS_JOBS_CDP_URL", "http://127.0.0.1:9223")


app = FastAPI(title="Org Intel Agent", version="0.1.0")
worker_stop = threading.Event()
worker_thread: threading.Thread | None = None


class OrgIntelRequest(BaseModel):
    company: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    mode: Literal["quick", "standard", "full"] = "standard"
    refresh: Literal["auto", "none", "jobs", "candidates", "all"] = "auto"
    client_request_id: str | None = None
    report: bool = True
    jobs_limit: int | None = None
    candidates_limit: int | None = None
    city: str = "100010000"
    candidate_city: str | None = None
    candidate_position: str = "不限职位"
    freshness_hours: int = 24
    jobs_cdp_url: str = DEFAULT_JOBS_CDP_URL
    candidates_cdp_url: str = DEFAULT_CANDIDATES_CDP_URL


class OrgIntelResponse(BaseModel):
    status: str
    job_id: str | None = None
    company: str
    eta_seconds: int | None = None
    eta_at: str | None = None
    message: str
    report_id: int | None = None
    report_markdown: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    progress: dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
def start_worker() -> None:
    global worker_thread
    conn = store.connect(DEFAULT_DB)
    conn.close()
    worker_thread = threading.Thread(target=worker_loop, name="org-intel-worker", daemon=True)
    worker_thread.start()


@app.on_event("shutdown")
def stop_worker() -> None:
    worker_stop.set()
    if worker_thread:
        worker_thread.join(timeout=5)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "org-intel-agent",
        "boss_cdp": {
            "candidates": DEFAULT_CANDIDATES_CDP_URL,
            "jobs": DEFAULT_JOBS_CDP_URL,
        },
    }


@app.post("/v1/org-intel/requests", response_model=OrgIntelResponse)
def create_org_intel_request(payload: OrgIntelRequest) -> OrgIntelResponse:
    aliases = normalize_aliases(payload.company, payload.aliases)
    request_data = payload.model_dump()
    request_data["aliases"] = aliases

    with store.connect(DEFAULT_DB) as conn:
        if payload.refresh == "auto":
            fresh_report = store.latest_report_for_company(conn, payload.company, payload.freshness_hours)
            if fresh_report:
                findings = store.latest_findings(conn, payload.company, fresh_report.get("id"))
                return OrgIntelResponse(
                    status="ready",
                    company=payload.company,
                    report_id=fresh_report.get("id"),
                    report_markdown=fresh_report.get("report_markdown"),
                    findings=findings,
                    message="已有新鲜组织情报报告，直接返回。",
                )

        active = store.get_active_job_for_company(conn, payload.company)
        if active:
            return job_to_response(conn, active, "已有同公司任务在执行，返回当前任务状态。")

        eta_seconds = estimate_eta_seconds(payload, conn)
        job = store.create_job(conn, request_data, eta_seconds)
        return job_to_response(conn, job, queued_message(payload, eta_seconds))


@app.get("/v1/org-intel/requests/{job_id}", response_model=OrgIntelResponse)
def get_org_intel_request(job_id: str) -> OrgIntelResponse:
    with store.connect(DEFAULT_DB) as conn:
        job = store.get_job(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job_to_response(conn, job, status_message(job))


def worker_loop() -> None:
    while not worker_stop.is_set():
        try:
            with store.connect(DEFAULT_DB) as conn:
                job = store.claim_next_job(conn)
            if job:
                process_job(job)
            else:
                time.sleep(POLL_SECONDS)
        except Exception as exc:
            print(f"[org-intel-worker] unexpected error: {exc}", file=sys.stderr)
            time.sleep(POLL_SECONDS)


def process_job(job: dict[str, Any]) -> None:
    request = job["request"]
    aliases = normalize_aliases(request["company"], request.get("aliases", []))
    refresh = request.get("refresh", "auto")
    freshness_hours = int(request.get("freshness_hours", 24))
    db_path = DEFAULT_DB

    try:
        if should_refresh_source(refresh, "jobs", db_path, aliases, freshness_hours):
            update_status(job["id"], "running_jobs", "jobs")
            run_file, command = run_capture_jobs(request)
            append_run(job["id"], "jobs", "ready", command, run_file)
            update_status(job["id"], "importing", "import_jobs")
            import_run(job["id"], run_file)
        else:
            append_run(job["id"], "jobs", "skipped", "fresh-data", None, None)

        if should_refresh_source(refresh, "candidates", db_path, aliases, freshness_hours):
            update_status(job["id"], "running_candidates", "candidates")
            run_file, command = run_capture_candidates(request)
            append_run(job["id"], "candidates", "ready", command, run_file)
            update_status(job["id"], "importing", "import_candidates")
            import_run(job["id"], run_file)
        else:
            append_run(job["id"], "candidates", "skipped", "fresh-data", None, None)

        report_id, report_path = (None, None)
        if request.get("report", True):
            update_status(job["id"], "generating_report", "report")
            report_id, report_path, command = run_report(request, aliases)
            append_run(job["id"], "report", "ready", command, report_path, None)

        with store.connect(DEFAULT_DB) as conn:
            store.update_job(
                conn,
                job["id"],
                status="ready",
                current_step="ready",
                finished_at=store.iso_now(),
                report_id=report_id,
                report_path=report_path,
            )
    except VerifyBlockedError as exc:
        fail_job(job["id"], "blocked_needs_human", str(exc))
    except CommandError as exc:
        fail_job(job["id"], "failed", str(exc))


def update_status(job_id: str, status: str, step: str) -> None:
    with store.connect(DEFAULT_DB) as conn:
        store.update_job(conn, job_id, status=status, current_step=step)


def append_run(
    job_id: str,
    run_type: str,
    status: str,
    command: str | None,
    run_file: Path | str | None,
    row_count: int | None = None,
    error_message: str | None = None,
) -> None:
    with store.connect(DEFAULT_DB) as conn:
        store.append_job_run(
            conn,
            job_id,
            run_type,
            status,
            command=command,
            run_file=str(run_file) if run_file else None,
            row_count=row_count,
            error_message=error_message,
        )


def fail_job(job_id: str, status: str, message: str) -> None:
    with store.connect(DEFAULT_DB) as conn:
        store.update_job(
            conn,
            job_id,
            status=status,
            current_step=status,
            error_message=message,
            finished_at=store.iso_now(),
        )
        store.append_job_run(conn, job_id, "pipeline", status, error_message=message)


def run_capture_jobs(request: dict[str, Any]) -> tuple[Path, str]:
    mode = request.get("mode", "standard")
    jobs_limit = int(request.get("jobs_limit") or default_jobs_limit(mode))
    command = [
        sys.executable,
        "python/boss_jobs_cdp_capture.py",
        "--company",
        request["company"],
        "--city",
        request.get("city") or "100010000",
        "--limit",
        str(jobs_limit),
        "--cdp-url",
        request.get("jobs_cdp_url") or DEFAULT_JOBS_CDP_URL,
        "--no-manual-ready",
    ]
    if mode == "quick":
        command.append("--no-details")
    return run_capture_command(command)


def run_capture_candidates(request: dict[str, Any]) -> tuple[Path, str]:
    mode = request.get("mode", "standard")
    candidates_limit = int(request.get("candidates_limit") or default_candidates_limit(mode))
    command = [
        sys.executable,
        "python/boss_cdp_capture.py",
        "--keyword",
        request["company"],
        "--position",
        request.get("candidate_position") or "不限职位",
        "--limit",
        str(candidates_limit),
        "--detail-max-pages",
        str(default_candidate_detail_pages(mode)),
        "--clear-filters",
        "--cdp-url",
        request.get("candidates_cdp_url") or DEFAULT_CANDIDATES_CDP_URL,
        "--no-manual-ready",
    ]
    if request.get("candidate_city"):
        command.extend(["--city", request["candidate_city"]])
    if mode == "quick":
        command.append("--no-details")
    return run_capture_command(command)


def import_run(job_id: str, run_file: Path) -> None:
    command = [
        sys.executable,
        "python/import_run_sqlite.py",
        str(run_file),
        "--db",
        str(DEFAULT_DB),
    ]
    run_command(command)
    append_run(job_id, "import", "ready", shell_join(command), run_file)


def run_report(request: dict[str, Any], aliases: list[str]) -> tuple[int | None, str | None, str]:
    command = [
        sys.executable,
        "python/org_report.py",
        "--company",
        request["company"],
        "--db",
        str(DEFAULT_DB),
        "--output-dir",
        DEFAULT_OUTPUT_DIR,
        "--since-days",
        "90",
    ]
    for alias in aliases:
        if alias != request["company"]:
            command.extend(["--alias", alias])
    output = run_command(command)
    report_path = extract_report_path(output)
    report_id = latest_report_id(request["company"], report_path)
    return report_id, report_path, shell_join(command)


def run_capture_command(command: list[str]) -> tuple[Path, str]:
    output = run_command(command)
    run_file = extract_run_file(output)
    if not run_file:
        raise CommandError("采集命令完成，但没有找到 run 文件路径。")
    return run_file, shell_join(command)


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        if is_verify_block(output):
            raise VerifyBlockedError(output.strip())
        raise CommandError(output.strip() or f"command failed: {shell_join(command)}")
    if is_verify_block(output):
        raise VerifyBlockedError(output.strip())
    return output


def extract_run_file(output: str) -> Path | None:
    match = re.search(r"单次运行结果：(.+)", output)
    return Path(match.group(1).strip()).resolve() if match else None


def extract_report_path(output: str) -> str | None:
    match = re.search(r"组织情报报告：(.+)", output)
    return match.group(1).strip() if match else None


def latest_report_id(company: str, report_path: str | None) -> int | None:
    with store.connect(DEFAULT_DB) as conn:
        row = conn.execute(
            """
            SELECT id FROM org_intel_reports
            WHERE company_name=? AND (? IS NULL OR report_path=?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (company, report_path, report_path),
        ).fetchone()
        return int(row["id"]) if row else None


def job_to_response(conn: Any, job: dict[str, Any], message: str) -> OrgIntelResponse:
    report = store.latest_report_by_id(conn, job.get("report_id"))
    findings = store.latest_findings(conn, job["company_name"], job.get("report_id")) if report else []
    return OrgIntelResponse(
        status=job["status"],
        job_id=job["id"],
        company=job["company_name"],
        eta_seconds=remaining_eta(job),
        eta_at=job.get("eta_at"),
        message=message,
        report_id=report.get("id") if report else job.get("report_id"),
        report_markdown=report.get("report_markdown") if report and job["status"] == "ready" else None,
        findings=findings if job["status"] == "ready" else [],
        progress=progress_for_job(conn, job),
    )


def progress_for_job(conn: Any, job: dict[str, Any]) -> dict[str, Any]:
    runs = store.get_job_runs(conn, job["id"])
    return {
        "current_step": job.get("current_step"),
        "runs": [
            {
                "run_type": item.get("run_type"),
                "status": item.get("status"),
                "run_file": item.get("run_file"),
                "error_message": item.get("error_message"),
            }
            for item in runs
        ],
    }


def remaining_eta(job: dict[str, Any]) -> int | None:
    if job["status"] in store.TERMINAL_STATUSES:
        return 0
    eta_at = store.parse_datetime(job.get("eta_at"))
    if not eta_at:
        return job.get("eta_seconds")
    return max(0, int((eta_at - datetime.now(timezone.utc)).total_seconds()))


def status_message(job: dict[str, Any]) -> str:
    if job["status"] == "ready":
        return "组织情报已生成。"
    if job["status"] == "blocked_needs_human":
        return "BOSS 触发登录/验证，需要人工处理后重新提交或等待 worker 重试。"
    if job["status"] == "failed":
        return job.get("error_message") or "组织情报任务失败。"
    return "组织情报任务正在执行。"


def estimate_eta_seconds(request: OrgIntelRequest, conn: Any) -> int:
    required_sources = refresh_sources_for_request(request)
    mode_base = {"quick": 600, "standard": 2100, "full": 5400}[request.mode]
    if request.report and not required_sources:
        mode_base = 90
    queued = conn.execute("SELECT COUNT(*) FROM org_intel_jobs WHERE status='queued'").fetchone()[0]
    return mode_base + int(queued) * mode_base


def queued_message(request: OrgIntelRequest, eta_seconds: int) -> str:
    required_sources = refresh_sources_for_request(request)
    if request.report and not required_sources:
        return f"{request.company} 已有新鲜原始数据，正在生成组织情报报告，预计 {human_eta(eta_seconds)}后可取。"
    source_text = "、".join(required_sources) if required_sources else "数据"
    return f"{request.company} 组织情报正在采集中，需要刷新 {source_text}，预计 {human_eta(eta_seconds)}后可取。"


def refresh_sources_for_request(request: OrgIntelRequest) -> list[str]:
    aliases = normalize_aliases(request.company, request.aliases)
    sources = []
    if should_refresh_source(request.refresh, "jobs", DEFAULT_DB, aliases, request.freshness_hours):
        sources.append("jobs")
    if should_refresh_source(request.refresh, "candidates", DEFAULT_DB, aliases, request.freshness_hours):
        sources.append("candidates")
    return sources


def human_eta(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} 分钟"


def default_jobs_limit(mode: str) -> int:
    return {"quick": 60, "standard": 120, "full": 200}.get(mode, 120)


def default_candidates_limit(mode: str) -> int:
    return {"quick": 60, "standard": 90, "full": 150}.get(mode, 90)


def default_candidate_detail_pages(mode: str) -> int:
    return {"quick": 1, "standard": 2, "full": 3}.get(mode, 2)


def is_verify_block(output: str) -> bool:
    return any(marker in output for marker in ("passport/zp/verify", "安全验证", "验证码", "进入登录/验证页"))


def shell_join(command: list[str]) -> str:
    return " ".join(command)


class CommandError(Exception):
    pass


class VerifyBlockedError(Exception):
    pass
