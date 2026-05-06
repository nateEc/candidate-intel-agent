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
from pydantic import BaseModel, Field

from boss_cdp_capture import CdpClient, request_json
from boss_login_flow import (
    LOGIN_URL,
    redact_phone,
    navigate_to,
    read_login_state,
    send_sms_code,
    start_recruiter_login,
    submit_sms_code,
)


DEFAULT_HOST = os.environ.get("HR_AGENT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("HR_AGENT_PORT", "8790"))
DEFAULT_CDP_PORT = int(os.environ.get("HR_AGENT_CDP_PORT", "9240"))
DEFAULT_CDP_URL = os.environ.get("HR_AGENT_CDP_URL", f"http://127.0.0.1:{DEFAULT_CDP_PORT}")
DEFAULT_PROFILE = os.environ.get("HR_AGENT_CHROME_PROFILE", "/tmp/boss-hr-agent-recruiter")
DEFAULT_START_URL = os.environ.get("HR_AGENT_START_URL", LOGIN_URL)


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


def run_with_client(action: Any) -> dict[str, Any]:
    config = get_browser_config()
    ensure_chrome(config["cdp_url"], int(config["cdp_port"]), config["profile"], config["start_url"])
    target = get_or_create_boss_target(config["cdp_url"], config["start_url"])
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


def get_or_create_boss_target(cdp_url: str, start_url: str) -> dict[str, Any]:
    try:
        targets = request_json(f"{cdp_url.rstrip('/')}/json/list")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"无法连接 Chrome CDP：{exc}") from exc

    for target in targets:
        if target.get("type") == "page" and "zhipin.com" in str(target.get("url", "")):
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
