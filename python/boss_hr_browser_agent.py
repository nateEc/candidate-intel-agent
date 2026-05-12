from __future__ import annotations

import os
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from boss_cdp_capture import CdpClient, request_json
from boss_job_publish_flow import (
    close_job,
    fill_job_publish_draft,
    fill_job_update_draft,
    read_job_publish_state,
    start_job_publish,
    start_job_update,
    submit_job_publish,
    submit_job_update,
)
from boss_login_flow import (
    LOGIN_URL,
    redact_phone,
    navigate_to,
    read_login_state,
    send_sms_code,
    start_recruiter_login,
    submit_sms_code,
)
from boss_recruiting_pipeline_flow import prepare_greeting, scan_applications, send_greeting
import talent_library
import talent_store


DEFAULT_HOST = os.environ.get("HR_AGENT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("HR_AGENT_PORT", "8790"))
DEFAULT_CDP_PORT = int(os.environ.get("HR_AGENT_CDP_PORT", "9240"))
DEFAULT_CDP_URL = os.environ.get("HR_AGENT_CDP_URL", f"http://127.0.0.1:{DEFAULT_CDP_PORT}")
DEFAULT_PROFILE = os.environ.get("HR_AGENT_CHROME_PROFILE", "/tmp/boss-hr-agent-recruiter")
DEFAULT_START_URL = os.environ.get("HR_AGENT_START_URL", LOGIN_URL)
DEFAULT_TALENT_DB = Path(os.environ.get("BOSS_TALENT_DB", "data-python/boss_talent.sqlite")).resolve()


app = FastAPI(title="BOSS HR Browser Agent", version="0.1.0")
state_lock = Lock()
browser_config_lock = Lock()
last_state: dict[str, Any] = {
    "status": "idle",
    "message": "BOSS HR Browser Agent 已就绪。",
}
browser_config: dict[str, Any] = {
    "cdp_url": DEFAULT_CDP_URL,
    "cdp_port": DEFAULT_CDP_PORT,
    "profile": DEFAULT_PROFILE,
    "start_url": DEFAULT_START_URL,
}


class BrowserStartRequest(BaseModel):
    start_url: str = DEFAULT_START_URL
    profile_dir: str = DEFAULT_PROFILE
    cdp_port: int = Field(default=DEFAULT_CDP_PORT, ge=1, le=65535)


class SendCodeRequest(BaseModel):
    phone: str = Field(min_length=7)


class SubmitCodeRequest(BaseModel):
    sms_code: str = Field(min_length=4, max_length=12)


class NavigateRequest(BaseModel):
    target: str = "talent_search"


class JobPublishDraftRequest(BaseModel):
    recruitment_type: str = "社招全职"
    job_title: str = Field(min_length=1, max_length=120)
    job_description: str = Field(min_length=1, max_length=5000)
    overseas_status: str = "境内岗位"
    job_type: str | None = None
    experience: str | None = None
    education: str | None = None
    salary_min_k: int | None = Field(default=None, ge=1, le=500)
    salary_max_k: int | None = Field(default=None, ge=1, le=500)
    salary_months: int | None = Field(default=None, ge=1, le=36)
    keywords: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_salary_order(self) -> "JobPublishDraftRequest":
        if self.salary_min_k is not None and self.salary_max_k is not None and self.salary_max_k < self.salary_min_k:
            raise ValueError("salary_max_k must be greater than or equal to salary_min_k")
        return self


class JobPublishSubmitRequest(BaseModel):
    confirm: bool = False


class JobUpdateStartRequest(BaseModel):
    job_title: str = Field(min_length=1, max_length=120)


class JobUpdateDraftRequest(BaseModel):
    job_description: str | None = Field(default=None, min_length=1, max_length=5000)
    overseas_status: str | None = None
    experience: str | None = None
    education: str | None = None
    salary_min_k: int | None = Field(default=None, ge=1, le=500)
    salary_max_k: int | None = Field(default=None, ge=1, le=500)
    salary_months: int | None = Field(default=None, ge=1, le=36)
    keywords: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_salary_order(self) -> "JobUpdateDraftRequest":
        if self.salary_min_k is not None and self.salary_max_k is not None and self.salary_max_k < self.salary_min_k:
            raise ValueError("salary_max_k must be greater than or equal to salary_min_k")
        return self


class JobCloseRequest(BaseModel):
    confirm: bool = False
    job_title: str | None = Field(default=None, max_length=120)


class ApplicationScanRequest(BaseModel):
    job_title: str | None = Field(default=None, max_length=120)
    job_filter: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=20, ge=1, le=200)
    include_resumes: bool = True
    detail_max_pages: int = Field(default=8, ge=1, le=20)
    detail_wait_ms: int = Field(default=1200, ge=0, le=10000)
    detail_scroll_delta: int = Field(default=620, ge=100, le=2000)
    detail_scroll_wait_ms: int = Field(default=900, ge=0, le=10000)
    profile_wait_ms: int = Field(default=1200, ge=0, le=10000)
    candidate_wait_ms: int = Field(default=2600, ge=0, le=30000)
    candidate_jitter_ms: int = Field(default=1400, ge=0, le=30000)
    dry_run: bool = True
    job_profile: dict[str, Any] = Field(default_factory=dict)
    output_dir: str = "data-python"


class GreetingPrepareRequest(BaseModel):
    quick_reply_index: int = Field(default=0, ge=0, le=20)
    message_text: str | None = Field(default=None, max_length=500)
    source_fingerprint: str | None = None
    job_title: str | None = Field(default=None, max_length=120)


class GreetingSendRequest(BaseModel):
    confirm: bool = False
    expected_text: str | None = Field(default=None, max_length=500)
    source_fingerprint: str | None = None
    job_title: str | None = Field(default=None, max_length=120)


@app.get("/health")
def health() -> dict[str, Any]:
    config = get_browser_config()
    return {
        "ok": True,
        "service": "boss-hr-browser-agent",
        "state": get_state(),
        "browser": {
            **config,
            "cdp_available": cdp_available(config["cdp_url"]),
        },
    }


@app.post("/v1/browser/start")
def start_browser(payload: BrowserStartRequest) -> dict[str, Any]:
    cdp_url = f"http://127.0.0.1:{payload.cdp_port}"
    update_browser_config(cdp_url, payload.cdp_port, payload.profile_dir, payload.start_url)
    ensure_chrome(cdp_url, payload.cdp_port, payload.profile_dir, payload.start_url)
    target = get_or_create_boss_target(cdp_url, payload.start_url)
    return update_state(
        {
            "status": "opening_login_page",
            "message": "已打开 BOSS 登录页。",
            "browser_url": cdp_url,
            "current_url": target.get("url"),
        }
    )


@app.post("/v1/boss/login/start")
def start_login() -> dict[str, Any]:
    return run_with_client(start_recruiter_login)


@app.post("/v1/boss/login/send-code")
def send_code(payload: SendCodeRequest) -> dict[str, Any]:
    phone = payload.phone.strip()

    def action(client: CdpClient) -> dict[str, Any]:
        result = send_sms_code(client, phone)
        result["phone_redacted"] = redact_phone(phone)
        return result

    return run_with_client(action)


@app.post("/v1/boss/login/submit-code")
def submit_code(payload: SubmitCodeRequest) -> dict[str, Any]:
    sms_code = payload.sms_code.strip()
    return run_with_client(lambda client: submit_sms_code(client, sms_code))


@app.get("/v1/boss/login/status")
def login_status() -> dict[str, Any]:
    return run_with_client(read_login_state)


@app.post("/v1/boss/navigate")
def navigate(payload: NavigateRequest) -> dict[str, Any]:
    return run_with_client(lambda client: navigate_to(client, payload.target))


@app.post("/v1/boss/job/publish/start")
def job_publish_start() -> dict[str, Any]:
    return run_with_client(start_job_publish)


@app.get("/v1/boss/job/publish/status")
def job_publish_status() -> dict[str, Any]:
    return run_with_client(read_job_publish_state)


@app.post("/v1/boss/job/publish/draft")
def job_publish_draft(payload: JobPublishDraftRequest) -> dict[str, Any]:
    return run_with_client(lambda client: fill_job_publish_draft(client, payload.model_dump()))


@app.post("/v1/boss/job/publish/submit")
def job_publish_submit(payload: JobPublishSubmitRequest) -> dict[str, Any]:
    return run_with_client(lambda client: submit_job_publish(client, payload.confirm))


@app.post("/v1/boss/job/update/start")
def job_update_start(payload: JobUpdateStartRequest) -> dict[str, Any]:
    return run_with_client(lambda client: start_job_update(client, payload.model_dump()))


@app.post("/v1/boss/job/update/draft")
def job_update_draft(payload: JobUpdateDraftRequest) -> dict[str, Any]:
    return run_with_client(lambda client: fill_job_update_draft(client, payload.model_dump()))


@app.post("/v1/boss/job/update/submit")
def job_update_submit(payload: JobPublishSubmitRequest) -> dict[str, Any]:
    return run_with_client(lambda client: submit_job_update(client, payload.confirm))


@app.post("/v1/boss/job/close")
def job_close(payload: JobCloseRequest) -> dict[str, Any]:
    return run_with_client(lambda client: close_job(client, payload.model_dump()))


@app.post("/v1/boss/applications/scan")
def applications_scan(payload: ApplicationScanRequest) -> dict[str, Any]:
    result = run_with_client(
        lambda client: scan_applications(client, payload.model_dump(), DEFAULT_TALENT_DB),
        preferred_url_part="/web/chat/index",
    )
    scan_run_id = result.get("scan_run_id")
    if scan_run_id and result.get("count", 0) > 0:
        if os.environ.get("DATABASE_URL"):
            try:
                with talent_library.connect() as conn:
                    result["talent_library_ingest"] = talent_library.ingest_boss_snapshot_from_sqlite(
                        conn,
                        DEFAULT_TALENT_DB,
                        scan_run_id=scan_run_id,
                    )
            except Exception as exc:
                result["talent_library_ingest"] = {"status": "failed", "message": str(exc)}
        else:
            result["talent_library_ingest"] = {
                "status": "skipped",
                "message": "DATABASE_URL 未配置，BOSS 采集结果仅保存在本地采集缓存。",
            }
    return result


@app.get("/v1/boss/applications/scan/{scan_run_id}")
def applications_scan_status(scan_run_id: str) -> dict[str, Any]:
    with talent_store.connect(DEFAULT_TALENT_DB) as conn:
        run = talent_store.get_scan_run(conn, scan_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="scan run not found")
    return {"status": run.get("status"), "scan_run_id": scan_run_id, "scan_run": run}


@app.post("/v1/boss/greetings/prepare")
def greetings_prepare(payload: GreetingPrepareRequest) -> dict[str, Any]:
    return run_with_client(
        lambda client: prepare_greeting(client, payload.model_dump()),
        preferred_url_part="/web/chat/index",
        require_preferred=True,
    )


@app.post("/v1/boss/greetings/send")
def greetings_send(payload: GreetingSendRequest) -> dict[str, Any]:
    return run_with_client(
        lambda client: send_greeting(client, payload.model_dump(), DEFAULT_TALENT_DB),
        preferred_url_part="/web/chat/index",
        require_preferred=True,
    )


def run_with_client(
    action: Any,
    *,
    preferred_url_part: str | None = None,
    require_preferred: bool = False,
) -> dict[str, Any]:
    config = get_browser_config()
    ensure_chrome(config["cdp_url"], int(config["cdp_port"]), config["profile"], config["start_url"])
    target = get_or_create_boss_target(config["cdp_url"], config["start_url"], preferred_url_part=preferred_url_part)
    if require_preferred and preferred_url_part and preferred_url_part not in str(target.get("url", "")):
        return update_state(
            {
                "status": "needs_manual",
                "message": "请先在 BOSS 沟通页选择一个候选人，再准备或发送打招呼消息。",
                "ok": False,
                "reason": "chat-page-not-open",
                "current_url": target.get("url"),
                "expected_url_part": preferred_url_part,
            }
        )
    client = CdpClient(target["webSocketDebuggerUrl"])
    try:
        result = action(client)
        return update_state(result)
    except Exception as exc:
        result = {"status": "failed", "message": str(exc)}
        update_state(result)
        raise HTTPException(status_code=500, detail=result)
    finally:
        client.close()


def ensure_chrome(cdp_url: str, cdp_port: int, profile_dir: str, start_url: str) -> None:
    if cdp_available(cdp_url):
        return

    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            "open",
            "-na",
            "Google Chrome",
            "--args",
            f"--remote-debugging-port={cdp_port}",
            f"--remote-allow-origins=http://127.0.0.1:{cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            start_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 12
    while time.time() < deadline:
        if cdp_available(cdp_url):
            return
        time.sleep(0.5)

    raise HTTPException(status_code=503, detail=f"Chrome CDP 未启动：{cdp_url}")


def cdp_available(cdp_url: str) -> bool:
    try:
        request_json(f"{cdp_url.rstrip('/')}/json/version")
        return True
    except Exception:
        return False


def get_or_create_boss_target(cdp_url: str, start_url: str, preferred_url_part: str | None = None) -> dict[str, Any]:
    try:
        targets = request_json(f"{cdp_url.rstrip('/')}/json/list")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Chrome CDP：{exc}") from exc

    boss_targets = [
        target
        for target in targets
        if target.get("type") == "page" and "zhipin.com" in str(target.get("url", ""))
    ]
    if preferred_url_part:
        for target in boss_targets:
            if preferred_url_part in str(target.get("url", "")):
                return target
    for target in boss_targets:
            return target

    encoded = urllib.parse.quote(start_url, safe="")
    return request_json(f"{cdp_url.rstrip('/')}/json/new?{encoded}", method="PUT")


def update_state(result: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **result,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with state_lock:
        last_state.clear()
        last_state.update(payload)
    return payload


def get_state() -> dict[str, Any]:
    with state_lock:
        return dict(last_state)


def update_browser_config(cdp_url: str, cdp_port: int, profile: str, start_url: str) -> None:
    with browser_config_lock:
        browser_config.update(
            {
                "cdp_url": cdp_url,
                "cdp_port": cdp_port,
                "profile": profile,
                "start_url": start_url,
            }
        )


def get_browser_config() -> dict[str, Any]:
    with browser_config_lock:
        return dict(browser_config)
